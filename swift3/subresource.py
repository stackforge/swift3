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

import re
import json
from functools import partial
from swift3.response import InvalidArgument, \
    S3NotImplemented, InvalidRequest, AccessDenied
from swift3.etree import Element, SubElement

XMLNS_XSI = 'http://www.w3.org/2001/XMLSchema-instance'

PERMISSIONS = ['FULL_CONTROL', 'READ', 'WRITE', 'READ_ACP', 'WRITE_ACP']

"""
S3's ACL Model:
AccessControlPolicy:
    Owner:
    AccessControlList:
        Grant[n]:
            (Grantee, Parmission)
"""


class Grantee(object):
    """
    Base class for grantee.

    :Definition (methods):
    init -> create a Grantee instance
    encode -> create a JSON which includes whole own elements
    elem -> create an ElementTree from itself

    NOTE: Needs confirmation whether we really need encode method or not.

    :Definition (static methods):
    from_header -> convert a grantee string in the HTTP header
                   to an Grantee instance.
    from_elem -> convert a ElementTree to an Grantee instance.

    TODO (not yet):
    NOTE: Needs confirmation whether we really need these methods or not.
    encode_from_elem -> convert from an ElementTree to a JSON
    elem_from_json -> convert from a JSON to an ElementTree
    from_json -> convert a Json string to an Grantee instance.
    """

    def __contains__(self, key):
        """
        The key argument is a S3 user id.  This method checks that the user id
        belongs to this class.
        """
        raise S3NotImplemented()

    def encode(self):
        """
        Represent this instance with JSON serializable types.
        """
        raise S3NotImplemented()

    def elem(self):
        """
        Get an etree element of this instance.
        """
        raise S3NotImplemented()

    @staticmethod
    def from_elem(elem):
        type = elem.get('{%s}type' % XMLNS_XSI)
        if type == 'CanonicalUser':
            value = elem.find('./ID').text
            return User(value)
        if type == 'Group':
            value = elem.find('./URI').text
            subclass = get_group_subclass_from_uri(value)
            return subclass()

    @staticmethod
    def from_header(grantee):
        """
        Convert a grantee string in the HTTP header to an Grantee instance.
        """
        type, value = grantee.split('=', 1)
        value = value.strip('"\'')
        if type == 'id':
            return User(value)
        elif type == 'emailAddress':
            raise S3NotImplemented()
        elif type == 'uri':
            # retrun a subclass instance of Group class
            subclass = get_group_subclass_from_uri(value)
            return subclass()
        else:
            raise InvalidArgument(type, value,
                                  'Argument format not recognized')


class User(Grantee):
    """
    Canonical user class for S3 accounts.
    """
    type = 'CanonicalUser'

    def __init__(self, name):
        self.id = name
        self.display_name = name

    def __contains__(self, key):
        return key == self.id

    def encode(self):
        return json.dumps(dict(id=self.id, display_name=self.display_name))

    def elem(self):
        elem = Element('Grantee', nsmap={'xsi': XMLNS_XSI})
        elem.set('{%s}type' % XMLNS_XSI, self.type)
        SubElement(elem, 'ID').text = self.id
        SubElement(elem, 'DisplayName').text = self.display_name
        return elem

    def __str__(self):
        return self.display_name


class Owner(object):
    """
    Owner class for S3 accounts
    """
    def __init__(self, id, name):
        self.id = id
        self.name = name


def get_group_subclass_from_uri(uri):
    """
    Convert a URI to one of the predefined groups.
    """
    for group in Group.__subclasses__():  # pylint: disable-msg=E1101
        if group.uri == uri:
            return group
    raise InvalidArgument('uri', uri, 'Invalid group uri')


class Group(Grantee):
    """
    Base class for Amazon S3 Predefined Groups
    """
    type = 'Group'
    uri = ''

    def __init__(self):
        # Initialize method to clarify we have nothing to do
        pass

    def encode(self):
        return json.dumps(dict(name=self.__class__.__name__))

    def elem(self):
        elem = Element('Grantee', nsmap={'xsi': XMLNS_XSI})
        elem.set('{%s}type' % XMLNS_XSI, self.type)
        SubElement(elem, 'URI').text = self.uri

        return elem

    def __str__(self):
        name = re.sub('(.)([A-Z])', r'\1 \2', self.__class__.__name__)
        return name + ' group'


def canned_acl_grantees(bucket_owner, object_owner=None):
    """
    A set of predefined grants supported by AWS S3.
    """
    owner = object_owner or bucket_owner

    return {
        'private': [
            ('FULL_CONTROL', User(owner.name)),
        ],
        'public-read': [
            ('READ', AllUsers()),
            ('FULL_CONTROL', User(owner.name)),
        ],
        'public-read-write': [
            ('READ', AllUsers()),
            ('WRITE', AllUsers()),
            ('FULL_CONTROL', User(owner.name)),
        ],
        'authenticated-read': [
            ('READ', AuthenticatedUsers()),
            ('FULL_CONTROL', User(owner.name)),
        ],
        'bucket-owner-read': [
            ('READ', User(bucket_owner.name)),
            ('FULL_CONTROL', User(owner.name)),
        ],
        'bucket-owner-full-control': [
            ('FULL_CONTROL', User(owner.name)),
            ('FULL_CONTROL', User(bucket_owner.name)),
        ],
        'log-delivery-write': [
            ('WRITE', LogDelivery()),
            ('READ_ACP', LogDelivery()),
            ('FULL_CONTROL', User(owner.name)),
        ],
    }


class AuthenticatedUsers(Group):
    """
    This group represents all AWS accounts.  Access permission to this group
    allows any AWS account to access the resource.  However, all requests must
    be signed (authenticated).
    """
    uri = 'http://acs.amazonaws.com/groups/global/AuthenticatedUsers'

    def __contains__(self, key):
        # Swift3 handles only signed requests.
        return True


class AllUsers(Group):
    """
    Access permission to this group allows anyone to access the resource.  The
    requests can be signed (authenticated) or unsigned (anonymous).  Unsigned
    requests omit the Authentication header in the request.

    Note: Swift3 regards unsigned requests as Swift API accesses, and bypasses
    them to Swift.  As a result, AllUsers behaves completely same as
    AuthenticatedUsers.
    """
    uri = 'http://acs.amazonaws.com/groups/global/AllUsers'

    def __contains__(self, key):
        return True


class LogDelivery(Group):
    """
    WRITE and READ_ACP permissions on a bucket enables this group to write
    server access logs to the bucket.
    """
    # TODO: Add support for log delivery group.
    pass


class Grant(object):
    """
    Grant Class which includes both Grantee and Permission
    """

    def __init__(self, grantee, permission):
        """
        :param grantee: a grantee class or its subclass
        :param permission: string
        """
        if permission.upper() not in PERMISSIONS:
            raise S3NotImplemented()
        if not isinstance(grantee, Grantee):
            raise

        self.grantee = grantee
        self.permission = permission

    @classmethod
    def from_elem(cls, elem):
        """
        Convert an ElementTree to an ACL instance
        """
        grantee = Grantee.from_elem(elem.find('./Grantee'))
        permission = elem.find('./Permission').text
        return cls(grantee, permission)

    def elem(self):
        """
        Create an etree element.
        """
        elem = Element('Grant')
        elem.append(self.grantee.elem())
        SubElement(elem, 'Permission').text = self.permission

        return elem

    def __iter__(self):
        yield self.permission
        yield self.grantee

    def __str__(self):
        return 'grantee: %s, permission: %s' % (self.grantee, self.permission)

    def allow(self, grantee, permission):
        return permission == self.permission and grantee in self.grantee


class ACL(object):
    """
    S3 ACL class.

    Refs (S3 API - acl-overview:
          http://docs.aws.amazon.com/AmazonS3/latest/dev/acl-overview.html):

    The sample ACL includes an Owner element identifying the owner via the
    AWS account's canonical user ID. The Grant element identifies the grantee
    (either an AWS account or a predefined group), and the permission granted.
    This default ACL has one Grant element for the owner. You grant permissions
    by adding Grant elements, each grant identifying the grantee and the
    permission.
    """
    metadata_name = 'acl'
    root_tag = 'AccessControlPolicy'
    max_xml_length = 200 * 1024

    def __init__(self, owner, grants=[]):
        """
        :param owner: Owner Class for ACL instance
        """
        self._owner = owner
        self.grants = grants

    @classmethod
    def from_elem(cls, elem):
        """
        Convert an ElementTree to an ACL instance
        """
        id = elem.find('./Owner/ID').text
        name = elem.find('./Owner/DisplayName').text
        grants = [Grant.from_elem(e)
                  for e in elem.findall('./AccessControlList/Grant')]
        return cls(Owner(id, name), grants)

    def elem(self):
        """
        Decode the value to an ACL instance.
        """
        elem = Element(self.root_tag)

        owner = SubElement(elem, 'Owner')
        SubElement(owner, 'ID').text = self._owner.id
        SubElement(owner, 'DisplayName').text = self._owner.name

        SubElement(elem, 'AccessControlList').extend(
            g.elem() for g in self.grants
        )

        return elem

    def owner(self):
        # FIXME: maybe we should return Owner instance
        return self._owner.id

    def check_owner(self, user_id):
        """
        Check that the user is an owner.
        """
        if user_id != self._owner.id:
            raise AccessDenied()

    def check_permission(self, user_id, permission):
        """
        Check that the user has a permission.
        """
        try:
            # owners have full control permission
            self.check_owner(user_id)
            return
        except AccessDenied:
            pass

        for g in self.grants:
            if g.allow(user_id, 'FULL_CONTROL') or \
                    g.allow(user_id, permission):
                return

        raise AccessDenied()

    @classmethod
    def from_headers(cls, headers, bucket_owner, object_owner=None):
        """
        Convert HTTP headers to an ACL instance.
        """
        grants = []
        try:
            for key, value in headers.items():
                if key.lower().startswith('x-amz-grant-'):
                    permission = key[len('x-amz-grant-'):]
                    permission = permission.upper().replace('-', '_')
                    for grantee in value.split(','):
                        grants.append(
                            Grant(Grantee.from_header(grantee), permission))

            if 'x-amz-acl' in headers:
                acl = headers['x-amz-acl']
                if len(grants) > 0:
                    err_msg = 'Specifying both Canned ACLs and Header ' \
                        'Grants is not allowed'
                    raise InvalidRequest(err_msg)

                grantees = canned_acl_grantees(bucket_owner, object_owner)[acl]
                for permission, grantee in grantees:
                    grants.append(Grant(grantee, permission))
        except (KeyError, ValueError):
            raise InvalidRequest()

        if len(grants) == 0:
            # No ACL headers
            return None

        return cls(object_owner or bucket_owner, grants)


class CannedACL(object):
    """
    A dict-like object that returns canned ACL.
    """
    def __getitem__(self, key):
        def acl(key, bucket_owner, object_owner=None):
            grants = []
            grantees = canned_acl_grantees(bucket_owner, object_owner)[key]
            for permission, grantee in grantees:
                grants.append(Grant(grantee, permission))
            return ACL(object_owner or bucket_owner, grants)

        return partial(acl, key)


canned_acl = CannedACL()

ACLPrivate = canned_acl['private']
ACLPublicRead = canned_acl['public-read']
ACLPublicReadWrite = canned_acl['public-read-write']
ACLAuthenticatedRead = canned_acl['authenticated-read']
ACLBucketOwnerRead = canned_acl['bucket-owner-read']
ACLBucketOwnerFullControl = canned_acl['bucket-owner-full-control']
ACLLogDeliveryWrite = canned_acl['log-delivery-write']
