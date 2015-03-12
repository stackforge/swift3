# Copyright (c) 2015 OpenStack Foundation
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
import datetime

from swift3.test.functional.s3_test_client import Connection
from swift3.test.functional.utils import get_error_code,\
    assert_common_response_headers, calculate_md5, calculate_datetime
from swift3.test.functional import Swift3FunctionalTestCase
from swift3.etree import fromstring


class TestSwift3Object(Swift3FunctionalTestCase):
    def setUp(self):
        super(TestSwift3Object, self).setUp()
        self.bucket = 'bucket'
        self.conn.make_request('PUT', self.bucket)

    def test_object(self):
        obj = 'object'
        contents = 'abc123'

        # PUT Object
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, body=contents)
        self.assertEquals(status, 200)

        assert_common_response_headers(self, headers)
        self.assertTrue(headers['etag'] is not None)
        self.assertEquals(headers['content-length'], '0')

        # PUT Object Copy
        self.conn.make_request('PUT', 'dst_bucket')
        headers = {'x-amz-copy-source': '/%s/%s' % (self.bucket, obj)}
        status, headers, body = \
            self.conn.make_request('PUT', 'dst_bucket', 'dst_obj',
                                   headers=headers)
        self.assertEquals(status, 200)

        assert_common_response_headers(self, headers)
        self.assertEquals(headers['content-length'], str(len(body)))

        elem = fromstring(body, 'CopyObjectResult')
        self.assertTrue(elem.find('LastModified').text is not None)
        self.assertTrue(elem.find('ETag').text is not None)

        # GET Object
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj)
        self.assertEquals(status, 200)

        assert_common_response_headers(self, headers)
        self.assertTrue(headers['last-modified'] is not None)
        self.assertTrue(headers['etag'] is not None)
        self.assertTrue(headers['content-type'] is not None)
        self.assertEquals(headers['content-length'], str(len(contents)))

        # HEAD Object
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        self.assertEquals(status, 200)

        assert_common_response_headers(self, headers)
        self.assertTrue(headers['last-modified'] is not None)
        self.assertTrue(headers['etag'] is not None)
        self.assertTrue(headers['content-type'] is not None)
        self.assertEquals(headers['content-length'], str(len(contents)))

        # DELETE Object
        status, headers, body = \
            self.conn.make_request('DELETE', self.bucket, obj)
        self.assertEquals(status, 204)

        assert_common_response_headers(self, headers)

    def test_put_object_error(self):
        auth_error_conn = Connection(aws_secret_key='invalid')
        status, headers, body = \
            auth_error_conn.make_request('PUT', self.bucket, 'object')
        self.assertEquals(get_error_code(body), 'SignatureDoesNotMatch')

        status, headers, body = \
            self.conn.make_request('PUT', 'bucket2', 'object')
        self.assertEquals(get_error_code(body), 'NoSuchBucket')

    def test_put_object_copy_error(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)
        dst_bucket = 'dst_bucket'
        self.conn.make_request('PUT', dst_bucket)
        dst_obj = 'dst_object'

        headers = {'x-amz-copy-source': '/%s/%s' % (self.bucket, obj)}
        auth_error_conn = Connection(aws_secret_key='invalid')
        status, headers, body = \
            auth_error_conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'SignatureDoesNotMatch')

        # /src/nothing -> /dst/dst
        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, 'nothing')}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'NoSuchKey')

        # /nothing/src -> /dst/dst
        headers = {'X-Amz-Copy-Source': '/%s/%s' % ('nothing', obj)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        # TODO: source bucket is not check.
        # self.assertEquals(get_error_code(body), 'NoSuchBucket')
        self.assertEquals(get_error_code(body), 'NoSuchKey')

        # /src/src -> /nothing/dst
        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj)}
        status, headers, body = \
            self.conn.make_request('PUT', 'nothing', dst_obj, headers)
        self.assertEquals(get_error_code(body), 'NoSuchBucket')

    def test_get_object_error(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        auth_error_conn = Connection(aws_secret_key='invalid')
        status, headers, body = \
            auth_error_conn.make_request('GET', self.bucket, obj)
        self.assertEquals(get_error_code(body), 'SignatureDoesNotMatch')

        status, headers, body = \
            self.conn.make_request('GET', self.bucket, 'invalid')
        self.assertEquals(get_error_code(body), 'NoSuchKey')

        status, headers, body = self.conn.make_request('GET', 'invalid', obj)
        # TODO; requires consideration
        # self.assertEquals(get_error_code(body), 'NoSuchBucket')
        self.assertEquals(get_error_code(body), 'NoSuchKey')

    def test_head_object_error(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        auth_error_conn = Connection(aws_secret_key='invalid')
        status, headers, body = \
            auth_error_conn.make_request('HEAD', self.bucket, obj)
        self.assertEquals(status, 403)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, 'invalid')
        self.assertEquals(status, 404)

        status, headers, body = \
            self.conn.make_request('HEAD', 'invalid', obj)
        self.assertEquals(status, 404)

    def test_delete_object_error(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        auth_error_conn = Connection(aws_secret_key='invalid')
        status, headers, body = \
            auth_error_conn.make_request('DELETE', self.bucket, obj)
        self.assertEquals(get_error_code(body), 'SignatureDoesNotMatch')

        status, headers, body = \
            self.conn.make_request('DELETE', self.bucket, 'invalid')
        self.assertEquals(get_error_code(body), 'NoSuchKey')

        status, headers, body = \
            self.conn.make_request('DELETE', 'invalid', obj)
        # TODO; requires consideration
        # self.assertEquals(get_error_code(body), 'NoSuchBucket')
        self.assertEquals(get_error_code(body), 'NoSuchKey')

    def test_put_object_content_encoding(self):
        obj = 'object'

        headers = {'Content-Encoding': 'gzip'}
        self.conn.make_request('PUT', self.bucket, obj, headers)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        self.assertEquals(headers['content-encoding'], 'gzip')

    def test_put_object_content_length(self):
        obj = 'object'
        contents = 'abcdefghij'

        # Content-Length with under body size
        headers = {'Content-Length': str(len(contents) - 1)}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)

        # connection reset for put data remains
        self.conn = Connection()
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, body='')
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-length'], str(len(contents) - 1))

        # Content-Length with invalid value
        headers = {'Content-Length': 'invalid'}
        self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        # TODO: S3 returns XML, but Swift3 returns nothing.
        # <Error>
        #   <Code>BadRequest</Code>
        #   <Message>An error occurred when parsing the HTTP request.</Message>
        #   <RequestId>[request_id]</RequestId>
        #   <HostId>[host_id]</HostId>
        # </Error>
        # self.assertEquals(get_error_code(body), 'BadRequest')
        self.assertEquals(status, 400)

    def test_put_object_content_md5(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'Content-MD5': calculate_md5(contents)}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)

        headers = {'Content-MD5': 'invalid'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(get_error_code(body), 'InvalidDigest')

    def test_put_object_content_type(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'Content-Type': 'text/plain'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        self.assertEquals(headers['content-type'], 'text/plain')

    def test_put_object_expect(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'Expect': '100-continue'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)

    def test_put_object_metadata(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'X-Amz-Meta-Bar': 'foo', 'X-Amz-Meta-Bar2': 'foo2'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        self.assertEquals(headers['x-amz-meta-bar'], 'foo')
        self.assertEquals(headers['x-amz-meta-bar2'], 'foo2')

    def test_put_object_storage_class(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'X-Amz-Storage-Class': 'STANDARD'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Storage-Class': 'REDUCED_REDUNDANCY'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        # TODO: REDUCED_REDUNDANCY is not supported.
        # self.assertEquals(status, 200)
        self.assertEquals(get_error_code(body), 'InvalidStorageClass')

        headers = {'X-Amz-Storage-Class': 'invalid'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(get_error_code(body), 'InvalidStorageClass')

    def test_put_object_website_redirect_location(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'X-Amz-Website-Redirect-Location':
                   'http://www.example.com/'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(get_error_code(body), 'NotImplemented')

    def test_put_object_server_side_encryption(self):
        obj = 'object'
        contents = 'abcdefghij'

        headers = {'X-Amz-Server-Side-Encryption':
                   'aws:kms'}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers, contents)
        self.assertEquals(get_error_code(body), 'NotImplemented')

    def test_put_object_copy(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        self.conn.make_request('PUT', dst_bucket)

        # /src/src -> /dst/dst
        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(status, 200)
        self.conn.make_request('DELETE', dst_bucket, dst_obj)

        # /src/src -> /src/dst
        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj)}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, dst_obj, headers)
        self.assertEquals(status, 200)
        self.conn.make_request('DELETE', self.bucket, dst_obj)

        # /src/src -> /src/src
        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj)}
        status, headers, body = \
            self.conn.make_request('PUT', self.bucket, obj, headers)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Copy-Source': '/%s/' % self.bucket}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'InvalidArgument')

        headers = {'X-Amz-Copy-Source': '/%s' % self.bucket}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'InvalidArgument')

        headers = {'X-Amz-Copy-Source': '/'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'InvalidArgument')

        headers = {'X-Amz-Copy-Source': '//'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'InvalidArgument')

    def test_put_object_copy_metadata_directive(self):
        obj = 'object'
        src_headers = {'X-Amz-Meta-Test': 'src'}
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        self.conn.make_request('PUT', self.bucket, obj, headers=src_headers)
        self.conn.make_request('PUT', dst_bucket)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Metadata-Directive': 'COPY',
                   'X-Amz-Meta-Test': 'dst'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(status, 200)
        status, headers, body = \
            self.conn.make_request('HEAD', dst_bucket, dst_obj)
        # TODO: COPY is not supported.
        # self.assertEquals(headers['x-amz-meta-test'], 'src')
        self.assertEquals(headers['x-amz-meta-test'], 'dst')
        self.conn.make_request('DELETE', dst_bucket, dst_obj)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Metadata-Directive': 'REPLACE',
                   'X-Amz-Meta-Test': 'dst'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(status, 200)
        status, headers, body = \
            self.conn.make_request('HEAD', dst_bucket, dst_obj)
        self.assertEquals(headers['x-amz-meta-test'], 'dst')
        self.conn.make_request('DELETE', dst_bucket, dst_obj)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Metadata-Directive': 'inavlid',
                   'X-Amz-Meta-Test': 'dst'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers)
        self.assertEquals(get_error_code(body), 'InvalidArgument')

    def test_put_object_copy_source_if_modified_since(self):
        obj = 'object'
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)
        self.conn.make_request('PUT', dst_bucket)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Modified-Since':
                   calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Modified-Since':
                   calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 412)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Modified-Since':
                   'invalid'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

    def test_put_object_copy_source_if_unmodified_since(self):
        obj = 'object'
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)
        self.conn.make_request('PUT', dst_bucket)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Unmodified-Since':
                   calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Unmodified-Since':
                   calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 412)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Unmodified-Since':
                   'invalid'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

    def test_put_object_copy_source_if_match(self):
        obj = 'object'
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        self.conn.make_request('PUT', self.bucket, obj)
        self.conn.make_request('PUT', dst_bucket)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Match': etag}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 412)

    def test_put_object_copy_source_if_none_match(self):
        obj = 'object'
        dst_bucket = 'dst_bucket'
        dst_obj = 'dst_object'
        self.conn.make_request('PUT', self.bucket, obj)
        self.conn.make_request('PUT', dst_bucket)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-None-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'X-Amz-Copy-Source': '/%s/%s' % (self.bucket, obj),
                   'X-Amz-Copy-Source-If-None-Match': etag}
        status, headers, body = \
            self.conn.make_request('PUT', dst_bucket, dst_obj, headers=headers)
        self.assertEquals(status, 412)

    def test_get_object_response_content_type(self):
        obj = 'obj'
        self.conn.make_request('PUT', self.bucket, obj)

        query = 'response-content-type=text/plain'
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, query=query)
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-type'], 'text/plain')

    def test_get_object_response_content_language(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        query = 'response-content-language=en'
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, query=query)
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-language'], 'en')

    def test_get_object_response_cache_control(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        query = 'response-cache-control=private'
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, query=query)
        self.assertEquals(status, 200)
        self.assertEquals(headers['cache-control'], 'private')

    def test_get_object_response_content_disposition(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        query = 'response-content-disposition=inline'
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, query=query)
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-disposition'], 'inline')

    def test_get_object_response_content_encoding(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        query = 'response-content-encoding=gzip'
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, query=query)
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-encoding'], 'gzip')

    def test_get_object_range(self):
        obj = 'object'
        contents = 'abcdefghij'
        self.conn.make_request('PUT', self.bucket, obj, body=contents)

        headers = {'Range': 'bytes=1-5'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 206)
        self.assertEquals(headers['content-length'], '5')
        self.assertEquals(len(body), 5)

        headers = {'Range': 'bytes=5-'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 206)
        self.assertEquals(headers['content-length'], '5')
        self.assertEquals(len(body), 5)

        headers = {'Range': 'bytes=-5'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 206)
        self.assertEquals(headers['content-length'], '5')
        self.assertEquals(len(body), 5)

        headers = {'Range': 'invalid'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)
        self.assertEquals(headers['content-length'], '10')
        self.assertEquals(len(body), 10)

    def test_get_object_if_modified_since(self):
        obj = 'object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)

        headers = {'If-Modified-Since': calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Modified-Since': calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 304)

        headers = {'If-Modified-Since': 'invalid'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

    def test_get_object_if_unmodified_since(self):
        obj = 'object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)

        headers = {'If-Unmodified-Since': calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Unmodified-Since': calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 412)

        headers = {'If-Unmodified-Since': 'invalid'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

    def test_get_object_if_match(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'If-Match': etag}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 412)

    def test_get_object_if_none_match(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'If-None-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-None-Match': etag}
        status, headers, body = \
            self.conn.make_request('GET', self.bucket, obj, headers=headers)
        self.assertEquals(status, 304)

    def test_head_object_range(self):
        obj = 'object'
        contents = 'abcdefghij'
        self.conn.make_request('PUT', self.bucket, obj, body=contents)

        headers = {'Range': 'bytes=1-5'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(headers['content-length'], '5')

        headers = {'Range': 'bytes=5-'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(headers['content-length'], '5')

        headers = {'Range': 'bytes=-5'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(headers['content-length'], '5')

        headers = {'Range': 'invalid'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(headers['content-length'], '10')

    def test_head_object_if_modified_since(self):
        obj = 'object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)

        headers = {'If-Modified-Since': calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Modified-Since': calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 304)

        headers = {'If-Modified-Since': 'invalid'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

    def test_head_object_if_unmodified_since(self):
        obj = 'object'
        date = datetime.datetime.utcnow()
        self.conn.make_request('PUT', self.bucket, obj)

        headers = {'If-Unmodified-Since': calculate_datetime(date, 1)}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Unmodified-Since': calculate_datetime(date, -1)}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 412)

        headers = {'If-Unmodified-Since': 'invalid'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

    def test_head_object_if_match(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'If-Match': etag}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 412)

    def test_head_object_if_none_match(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj)
        etag = headers['etag']

        headers = {'If-None-Match': 'none-match'}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 200)

        headers = {'If-None-Match': etag}
        status, headers, body = \
            self.conn.make_request('HEAD', self.bucket, obj, headers=headers)
        self.assertEquals(status, 304)

    def test_delete_object_mfa(self):
        obj = 'object'
        self.conn.make_request('PUT', self.bucket, obj)

        headers = {'X-Amz-Mfa': '20899872 301749'}
        status, headers, body = \
            self.conn.make_request('DELETE', self.bucket, obj, headers)
        self.assertEquals(get_error_code(body), 'NotImplemented')

if __name__ == '__main__':
    unittest.main()
