# Copyright (c) 2014 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from swift3.subresource import ACL, Owner
from swift3.response import NoSuchKey, \
    MissingSecurityHeader, MalformedACLError, UnexpectedContent
from swift3.etree import fromstring, XMLSyntaxError, DocumentInvalid
from swift3.utils import LOGGER, MULTIUPLOAD_SUFFIX

from swift.common.utils import split_path

"""
Acl Handlers:

Why do we need this:
To make controller classes clean, we need these handlers.
It is really useful for customizing acl checking algorithms for
each controller.

Basic Information:
BaseAclHandler wraps basic Acl handling.
(i.e. it will check acl from ACL_MAP by using HEAD)

How to extend:
Make a handler with the name of the controller.
(e.g. BucketAclHandler is for BucketController)
It consists of method(s) for actual S3 method on controllers as follows.

e.g.:
class BucketAclHandler(BaseAclHandler):
   def PUT:
       << put acl handling algorithms here for PUT bucket >>

NOTE:
If the method DON'T need to recall _get_response in outside of
acl checking, the method have to return the response it needs at
the end of method.
"""


def get_acl(headers, body, bucket_owner, object_owner=None):
    """
    Get ACL instance from S3 (e.g. x-amz-grant) headers or S3 acl xml body.
    """
    acl = ACL.from_headers(headers, bucket_owner, object_owner,
                           as_private=False)

    if acl is None:
        # Get acl from request body if possible.
        if not body:
            msg = 'Your request was missing a required header'
            raise MissingSecurityHeader(msg, missing_header_name='x-amz-acl')
        try:
            elem = fromstring(body, ACL.root_tag)
            acl = ACL.from_elem(elem)
        except(XMLSyntaxError, DocumentInvalid):
            raise MalformedACLError()
        except Exception as e:
            LOGGER.error(e)
            raise
    else:
        if body:
            # Specifying grant with both header and xml is not allowed.
            raise UnexpectedContent

    return acl


def get_acl_handler(controller_name):
    # pylint: disable-msg=E1101
    for handler in BaseAclHandler.__subclasses__():
        handler_suffix_len = len('AclHandler') \
            if not handler.__name__ == 'S3AclHandler' else len('Hanlder')
        if handler.__name__[:-handler_suffix_len] == controller_name:
            return handler

    return BaseAclHandler


class BaseAclHandler(object):
    """
    BaseAclHandler: Handling ACL for basic requests mapped on ACL_MAP
    """
    def __init__(self, req, container, obj):
        self.req = req
        self.container = self.req.container_name if container is None \
            else container
        self.obj = self.req.object_name if obj is None else obj
        self.method = req.environ['REQUEST_METHOD']
        self.user_id = self.req.user_id

    def _check_copy_source(self, app):
        if 'X-Amz-Copy-Source' in self.req.headers:
            src_path = self.req.headers['X-Amz-Copy-Source']
            src_path = src_path if src_path.startswith('/') else \
                ('/' + src_path)
            src_bucket, src_obj = split_path(src_path, 0, 2, True)
            self._handle_acl(app, 'HEAD', src_bucket, src_obj, 'READ')

    def handle_acl(self, app, method):
        method = method or self.method
        if hasattr(self, method):
            return getattr(self, method)(app)
        else:
            return self._handle_acl(app, method)

    def _handle_acl(self, app, sw_method, container=None, obj=None,
                    permission=None):
        """
        General acl handling method.
        This method expects to call Request._get_response() in outside of
        this method so that this method returns resonse only when sw_method
        is HEAD.
        """
        container = self.container if container is None else container
        obj = self.obj if obj is None else obj
        sw_method = sw_method or self.req.environ['REQUEST_METHOD']
        resource = 'object' if obj else 'container'

        if not permission and (self.method, sw_method, resource) in ACL_MAP:
            acl_check = ACL_MAP[(self.method, sw_method, resource)]
            resource = acl_check.get('Resource') or resource
            permission = acl_check['Permission']
        if not permission:
            raise Exception('No permission to be checked exists')

        if container.endswith(MULTIUPLOAD_SUFFIX):
            container = container[:-len(MULTIUPLOAD_SUFFIX)]

        if resource == 'object':
            resp = self.req.get_acl_response(app, 'HEAD',
                                             container, obj)
            acl = resp.object_acl
        elif resource == 'container':
            resp = self.req.get_acl_response(app, 'HEAD',
                                             container, '')
            acl = resp.bucket_acl

        acl.check_permission(self.user_id, permission)

        if sw_method == 'HEAD':
            return resp


class BucketAclHandler(BaseAclHandler):
    """
    BucketAclHandler: Handler for BucketController
    """
    def PUT(self, app):
        req_acl = ACL.from_headers(self.req.headers,
                                   Owner(self.user_id, self.user_id))

        # To avoid overwriting the existing bucket's ACL, we send PUT
        # request first before setting the ACL to make sure that the target
        # container does not exist.
        self.req.get_acl_response(app, 'PUT')

        # update metadata
        self.req.bucket_acl = req_acl

        # FIXME If this request is failed, there is a possibility that the
        # bucket which has no ACL is left.
        return self.req.get_acl_response(app, 'POST')


class ObjectAclHandler(BaseAclHandler):
    """
    ObjectAclHandler: Handler for ObjectController
    """
    def PUT(self, app):
        self._check_copy_source(app)

        b_resp = self._handle_acl(app, 'HEAD', obj='')
        # To avoid overwriting the existing object by unauthorized user,
        # we send HEAD request first before writing the object to make
        # sure that the target object does not exist or the user that sent
        # the PUT request have write permission.
        try:
            self._handle_acl(app, 'HEAD')
        except NoSuchKey:
            pass
        req_acl = ACL.from_headers(self.req.headers,
                                   b_resp.bucket_acl.owner,
                                   Owner(self.user_id, self.user_id))
        self.req.object_acl = req_acl


class S3AclHandler(BaseAclHandler):
    """
    S3AclHandler: Handler for S3AclController
    """
    def GET(self, app):
        self._handle_acl(app, 'HEAD', permission='READ_ACP')

    def PUT(self, app):
        if self.req.is_object_request:
            b_resp = self.req.get_acl_response(app, 'HEAD', obj='')
            o_resp = self._handle_acl(app, 'HEAD', permission='WRITE_ACP')
            req_acl = get_acl(self.req.headers,
                              self.req.xml(ACL.max_xml_length),
                              b_resp.bucket_acl.owner,
                              o_resp.object_acl.owner)

            # Don't change the owner of the resource by PUT acl request.
            o_resp.object_acl.check_owner(req_acl.owner.id)

            for g in req_acl.grants:
                LOGGER.debug('Grant %s %s permission on the object /%s/%s' %
                             (g.grantee, g.permission, self.req.container_name,
                              self.req.object_name))
            self.req.object_acl = req_acl
        else:
            self._handle_acl(app, self.method)

    def POST(self, app):
        if self.req.is_bucket_request:
            resp = self._handle_acl(app, 'HEAD', permission='WRITE_ACP')

            req_acl = get_acl(self.req.headers,
                              self.req.xml(ACL.max_xml_length),
                              resp.bucket_acl.owner)

            # Don't change the owner of the resource by PUT acl request.
            resp.bucket_acl.check_owner(req_acl.owner.id)

            for g in req_acl.grants:
                LOGGER.debug('Grant %s %s permission on the bucket /%s' %
                             (g.grantee, g.permission,
                              self.req.container_name))
            self.req.bucket_acl = req_acl
        else:
            self._handle_acl(app, self.method)


class MultiObjectDeleteAclHandler(BaseAclHandler):
    def DELETE(self, app):
        # Only bucket write acl is required
        pass


class PartAclHandler(BaseAclHandler):
    def PUT(self, app):
        self._check_copy_source(app)
        self._handle_acl(app, 'PUT')

    def HEAD(self, app):
        # For _check_upload_info
        pass


class UploadsAclHandler(BaseAclHandler):
    def PUT(self, app):
        if not self.obj:
            # Initiate Multipart Uploads (put +segment container)
            self._handle_acl(
                app, 'PUT',
                container=self.container[:-len(MULTIUPLOAD_SUFFIX)])
        # Initiate Multipart Uploads (put upload id object)


class UploadAclHandler(BaseAclHandler):
    def HEAD(self, app):
        # abort multiupload
        if self.method == 'DELETE' and self.obj:
            self._handle_acl(
                app, 'HEAD',
                container=self.container[:-len(MULTIUPLOAD_SUFFIX)])

    def PUT(self, app):
        """
        Complete upload
        """
        if self.req.is_bucket_request:
            self._handle_acl(app, 'PUT')

    def GET(self, app):
        if self.req.is_object_request:
            """
            List parts / Complete Multiupload
            """
            if self.method is not 'DELETE':
                self._handle_acl(app, 'GET', obj='')

    def DELETE(self, app):
        """
        DELETE upload_id object for complete upload
        """
        if self.req.is_object_request:
            """
            DELETE objects at abort multipart upload
            """
            pass


"""
ACL_MAP =
    {
        ('<s3_method>', '<swift_method>', '<swift_resource>'):
        {'Resource': '<check_resource>',
         'Permission': '<check_permission>'},
        ...
    }

s3_method: Method of S3 Request from user to swift3
swift_method: Method of Swift Request from swift3 to swift
swift_resource: Resource of Swift Request from swift3 to swift
check_resource: <container/object>
check_permission: <OWNER/READ/WRITE/READ_ACP/WRITE_ACP>
"""
ACL_MAP = {
    # HEAD Bucket
    ('HEAD', 'HEAD', 'container'):
    {'Permission': 'READ'},
    # GET Service
    ('GET', 'HEAD', 'container'):
    {'Permission': 'OWNER'},
    # GET Bucket, List Parts, List Multipart Upload
    ('GET', 'GET', 'container'):
    {'Permission': 'READ'},
    # PUT Object, PUT Object Copy
    ('PUT', 'HEAD', 'container'):
    {'Permission': 'WRITE'},
    # DELETE Bucket
    ('DELETE', 'DELETE', 'container'):
    {'Permission': 'OWNER'},
    # HEAD Object
    ('HEAD', 'HEAD', 'object'):
    {'Permission': 'READ'},
    # GET Object
    ('GET', 'GET', 'object'):
    {'Permission': 'READ'},
    # PUT Object, PUT Object Copy
    ('PUT', 'HEAD', 'object'):
    {'Permission': 'WRITE'},
    # Complete Multipart Upload
    ('POST', 'GET', 'container'):
    {'Permission': 'WRITE'},
    # Initiate Multipart Upload
    ('POST', 'PUT', 'container'):
    {'Permission': 'WRITE'},
    # Abort Multipart Upload
    ('DELETE', 'HEAD', 'object'):
    {'Resource': 'container',
     'Permission': 'WRITE'},
    # Upload Part
    ('PUT', 'PUT', 'object'):
    {'Resource': 'container',
     'Permission': 'WRITE'},
    # Delete Object
    ('DELETE', 'DELETE', 'object'):
    {'Resource': 'container',
     'Permission': 'WRITE'},
    # DELETE Multiple Objects
    ('POST', 'HEAD', 'container'):
    {'Permission': 'WRITE'},
}
