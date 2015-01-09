# Copyright (c) 2011-2014 OpenStack Foundation.
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

import unittest
from mock import patch
from contextlib import nested
from datetime import datetime
import hashlib
import base64
from urllib import unquote, quote

from swift.common import swob
from swift.common.swob import Request

from swift3.test.unit import Swift3TestCase
from swift3.request import Request as S3Request
from swift3.etree import fromstring
from swift3.middleware import Swift3Middleware


class TestSwift3Middleware(Swift3TestCase):
    def setUp(self):
        super(TestSwift3Middleware, self).setUp()

        self.swift.register('GET', '/something', swob.HTTPOk, {}, 'FAKE APP')

    def test_non_s3_request_passthrough(self):
        req = Request.blank('/something')
        status, headers, body = self.call_swift3(req)
        self.assertEquals(body, 'FAKE APP')

    def test_bad_format_authorization(self):
        req = Request.blank('/something',
                            headers={'Authorization': 'hoge'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'AccessDenied')

    def test_bad_method(self):
        req = Request.blank('/',
                            environ={'REQUEST_METHOD': 'PUT'},
                            headers={'Authorization': 'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'MethodNotAllowed')

    def test_path_info_encode(self):
        bucket_name = 'b%75cket'
        object_name = 'ob%6aect:1'
        self.swift.register('GET', '/v1/AUTH_test/bucket/object:1',
                            swob.HTTPOk, {}, None)
        req = Request.blank('/%s/%s' % (bucket_name, object_name),
                            environ={'REQUEST_METHOD': 'GET'},
                            headers={'Authorization': 'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        raw_path_info = "/%s/%s" % (bucket_name, object_name)
        path_info = req.environ['PATH_INFO']
        self.assertEquals(path_info, unquote(raw_path_info))
        self.assertEquals(req.path, quote(path_info))

    def test_canonical_string(self):
        """
        The hashes here were generated by running the same requests against
        boto.utils.canonical_string
        """
        def canonical_string(path, headers):
            if '?' in path:
                path, query_string = path.split('?', 1)
            else:
                query_string = ''

            req = S3Request({
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': path,
                'QUERY_STRING': query_string,
                'HTTP_AUTHORIZATION': 'AWS X:Y:Z',
            })
            req.headers.update(headers)
            return req._canonical_string()

        def verify(hash, path, headers):
            s = canonical_string(path, headers)
            self.assertEquals(hash, hashlib.md5(s).hexdigest())

        verify('6dd08c75e42190a1ce9468d1fd2eb787', '/bucket/object',
               {'Content-Type': 'text/plain', 'X-Amz-Something': 'test',
                'Date': 'whatever'})

        verify('c8447135da232ae7517328f3429df481', '/bucket/object',
               {'Content-Type': 'text/plain', 'X-Amz-Something': 'test'})

        verify('bf49304103a4de5c325dce6384f2a4a2', '/bucket/object',
               {'content-type': 'text/plain'})

        verify('be01bd15d8d47f9fe5e2d9248cc6f180', '/bucket/object', {})

        verify('e9ec7dca45eef3e2c7276af23135e896', '/bucket/object',
               {'Content-MD5': 'somestuff'})

        verify('a822deb31213ad09af37b5a7fe59e55e', '/bucket/object?acl', {})

        verify('cce5dd1016595cb706c93f28d3eaa18f', '/bucket/object',
               {'Content-Type': 'text/plain', 'X-Amz-A': 'test',
                'X-Amz-Z': 'whatever', 'X-Amz-B': 'lalala',
                'X-Amz-Y': 'lalalalalalala'})

        verify('7506d97002c7d2de922cc0ec34af8846', '/bucket/object',
               {'Content-Type': None, 'X-Amz-Something': 'test'})

        verify('28f76d6162444a193b612cd6cb20e0be', '/bucket/object',
               {'Content-Type': None,
                'X-Amz-Date': 'Mon, 11 Jul 2011 10:52:57 +0000',
                'Date': 'Tue, 12 Jul 2011 10:52:57 +0000'})

        verify('ed6971e3eca5af4ee361f05d7c272e49', '/bucket/object',
               {'Content-Type': None,
                'Date': 'Tue, 12 Jul 2011 10:52:57 +0000'})

        verify('41ecd87e7329c33fea27826c1c9a6f91', '/bucket/object?cors', {})

        verify('d91b062f375d8fab407d6dab41fd154e', '/bucket/object?tagging',
               {})

        verify('ebab878a96814b30eb178e27efb3973f', '/bucket/object?restore',
               {})

        verify('f6bf1b2d92b054350d3679d28739fc69', '/bucket/object?'
               'response-cache-control&response-content-disposition&'
               'response-content-encoding&response-content-language&'
               'response-content-type&response-expires', {})

        str1 = canonical_string('/', headers={'Content-Type': None,
                                              'X-Amz-Something': 'test'})
        str2 = canonical_string('/', headers={'Content-Type': '',
                                              'X-Amz-Something': 'test'})
        str3 = canonical_string('/', headers={'X-Amz-Something': 'test'})

        self.assertEquals(str1, str2)
        self.assertEquals(str2, str3)

    def test_signed_urls_expired(self):
        expire = '1000000000'
        req = Request.blank('/bucket/object?Signature=X&Expires=%s&'
                            'AWSAccessKeyId=test:tester' % expire,
                            environ={'REQUEST_METHOD': 'GET'})
        req.headers['Date'] = datetime.utcnow()
        req.content_type = 'text/plain'
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'AccessDenied')

    def test_signed_urls(self):
        expire = '10000000000'
        req = Request.blank('/bucket/object?Signature=X&Expires=%s&'
                            'AWSAccessKeyId=test:tester' % expire,
                            environ={'REQUEST_METHOD': 'GET'})
        req.headers['Date'] = datetime.utcnow()
        req.content_type = 'text/plain'
        status, headers, body = self.call_swift3(req)
        self.assertEquals(status.split()[0], '200')
        for _, _, headers in self.swift.calls_with_headers:
            self.assertEquals(headers['Authorization'], 'AWS test:tester:X')
            self.assertEquals(headers['Date'], expire)

    def test_signed_urls_invalid_expire(self):
        expire = 'invalid'
        req = Request.blank('/bucket/object?Signature=X&Expires=%s&'
                            'AWSAccessKeyId=test:tester' % expire,
                            environ={'REQUEST_METHOD': 'GET'})
        req.headers['Date'] = datetime.utcnow()
        req.content_type = 'text/plain'
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'AccessDenied')

    def test_signed_urls_no_sign(self):
        expire = 'invalid'
        req = Request.blank('/bucket/object?Expires=%s&'
                            'AWSAccessKeyId=test:tester' % expire,
                            environ={'REQUEST_METHOD': 'GET'})
        req.headers['Date'] = datetime.utcnow()
        req.content_type = 'text/plain'
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'AccessDenied')

    def test_bucket_virtual_hosted_style(self):
        req = Request.blank('/',
                            environ={'HTTP_HOST': 'bucket.localhost:80',
                                     'REQUEST_METHOD': 'HEAD',
                                     'HTTP_AUTHORIZATION':
                                     'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(status.split()[0], '200')

    def test_object_virtual_hosted_style(self):
        req = Request.blank('/object',
                            environ={'HTTP_HOST': 'bucket.localhost:80',
                                     'REQUEST_METHOD': 'HEAD',
                                     'HTTP_AUTHORIZATION':
                                     'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(status.split()[0], '200')

    def test_token_generation(self):
        self.swift.register('HEAD', '/v1/AUTH_test/bucket+segments/'
                                    'object/123456789abcdef',
                            swob.HTTPOk, {}, None)
        self.swift.register('PUT', '/v1/AUTH_test/bucket+segments/'
                                   'object/123456789abcdef/1',
                            swob.HTTPCreated, {}, None)
        req = Request.blank('/bucket/object?uploadId=123456789abcdef'
                            '&partNumber=1',
                            environ={'REQUEST_METHOD': 'PUT'})
        req.headers['Authorization'] = 'AWS test:tester:hmac'
        status, headers, body = self.call_swift3(req)
        _, _, headers = self.swift.calls_with_headers[-1]
        self.assertEquals(base64.urlsafe_b64decode(
            headers['X-Auth-Token']),
            'PUT\n\n\n/bucket/object?partNumber=1&uploadId=123456789abcdef')

    def test_invalid_uri(self):
        req = Request.blank('/bucket/invalid\xffname',
                            environ={'REQUEST_METHOD': 'GET'},
                            headers={'Authorization': 'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'InvalidURI')

    def test_object_create_bad_md5_unreadable(self):
        req = Request.blank('/bucket/object',
                            environ={'REQUEST_METHOD': 'PUT',
                                     'HTTP_AUTHORIZATION': 'AWS X:Y:Z',
                                     'HTTP_CONTENT_MD5': '#'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'InvalidDigest')

    def test_invalid_metadata_directive(self):
        req = Request.blank('/',
                            environ={'REQUEST_METHOD': 'GET',
                                     'HTTP_AUTHORIZATION': 'AWS X:Y:Z',
                                     'HTTP_X_AMZ_METADATA_DIRECTIVE':
                                     'invalid'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'InvalidArgument')

    def test_invalid_storage_class(self):
        req = Request.blank('/',
                            environ={'REQUEST_METHOD': 'GET',
                                     'HTTP_AUTHORIZATION': 'AWS X:Y:Z',
                                     'HTTP_X_AMZ_STORAGE_CLASS': 'INVALID'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'InvalidStorageClass')

    def _test_unsupported_header(self, header):
        req = Request.blank('/error',
                            environ={'REQUEST_METHOD': 'GET',
                                     'HTTP_AUTHORIZATION': 'AWS X:Y:Z'},
                            headers={'x-amz-' + header: 'value'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'NotImplemented')

    def test_mfa(self):
        self._test_unsupported_header('mfa')

    def test_server_side_encryption(self):
        self._test_unsupported_header('server-side-encryption')

    def test_website_redirect_location(self):
        self._test_unsupported_header('website-redirect-location')

    def _test_unsupported_resource(self, resource):
        req = Request.blank('/error?' + resource,
                            environ={'REQUEST_METHOD': 'GET',
                                     'HTTP_AUTHORIZATION': 'AWS X:Y:Z'})
        status, headers, body = self.call_swift3(req)
        self.assertEquals(self._get_error_code(body), 'NotImplemented')

    def test_notification(self):
        self._test_unsupported_resource('notification')

    def test_policy(self):
        self._test_unsupported_resource('policy')

    def test_request_payment(self):
        self._test_unsupported_resource('requestPayment')

    def test_torrent(self):
        self._test_unsupported_resource('torrent')

    def test_website(self):
        self._test_unsupported_resource('website')

    def test_cors(self):
        self._test_unsupported_resource('cors')

    def test_tagging(self):
        self._test_unsupported_resource('tagging')

    def test_restore(self):
        self._test_unsupported_resource('restore')

    def test_unsupported_method(self):
        req = Request.blank('/bucket?acl',
                            environ={'REQUEST_METHOD': 'POST'},
                            headers={'Authorization': 'AWS test:tester:hmac'})
        status, headers, body = self.call_swift3(req)
        elem = fromstring(body, 'Error')
        self.assertEquals(elem.find('./Code').text, 'MethodNotAllowed')
        self.assertEquals(elem.find('./Method').text, 'POST')
        self.assertEquals(elem.find('./ResourceType').text, 'ACL')

    def test_check_pipeline(self):
        with nested(patch("swift3.middleware.CONF"),
                    patch("swift3.middleware.PipelineWrapper"),
                    patch("swift3.middleware.loadcontext")) as \
                (conf, pipeline, _):
            conf.pipeline_check = True
            conf.__file__ = ''

            pipeline.return_value = 'swift3 tempauth proxy-server'
            self.swift3.check_pipeline(conf)

            pipeline.return_value = 'swift3 s3token authtoken keystoneauth ' \
                'proxy-server'
            self.swift3.check_pipeline(conf)

            pipeline.return_value = 'swift3 swauth proxy-server'
            self.swift3.check_pipeline(conf)

            pipeline.return_value = 'swift3 authtoken s3token keystoneauth ' \
                'proxy-server'
            with self.assertRaises(ValueError):
                self.swift3.check_pipeline(conf)

            pipeline.return_value = 'swift3 proxy-server'
            with self.assertRaises(ValueError):
                self.swift3.check_pipeline(conf)

            pipeline.return_value = 'proxy-server'
            with self.assertRaises(ValueError):
                self.swift3.check_pipeline(conf)

    def test_swift3_initialization_with_disabled_pipeline_check(self):
        with nested(patch("swift3.middleware.CONF"),
                    patch("swift3.middleware.PipelineWrapper"),
                    patch("swift3.middleware.loadcontext")) as \
                (conf, pipeline, _):
            # Disable pipeline check
            conf.pipeline_check = False
            conf.__file__ = ''

            pipeline.return_value = 'swift3 tempauth proxy-server'
            Swift3Middleware(self.app, conf)

            pipeline.return_value = 'swift3 s3token authtoken keystoneauth ' \
                'proxy-server'
            Swift3Middleware(self.app, conf)

            pipeline.return_value = 'swift3 swauth proxy-server'
            Swift3Middleware(self.app, conf)

            pipeline.return_value = 'swift3 authtoken s3token keystoneauth ' \
                'proxy-server'
            Swift3Middleware(self.app, conf)

            pipeline.return_value = 'swift3 proxy-server'
            Swift3Middleware(self.app, conf)

            pipeline.return_value = 'proxy-server'
            Swift3Middleware(self.app, conf)


if __name__ == '__main__':
    unittest.main()
