# Copyright 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
import base64
import json
import logging
import time
import unittest
import uuid

import fixtures
import mock
import requests
from requests_mock.contrib import fixture as rm_fixture
from six.moves import urllib

from swift3 import s3_token_middleware as s3_token
from swift.common.swob import Request, Response
from swift.common.wsgi import ConfigFileError

GOOD_RESPONSE = {'access': {
    'user': {
        'username': 'S3_USER',
        'name': 'S3_USER',
        'id': 'USER_ID',
        'roles': [
            {'name': 'swift-user'},
            {'name': '_member_'},
        ],
    },
    'token': {
        'id': 'TOKEN_ID',
        'tenant': {
            'id': 'TENANT_ID',
            'name': 'TENANT_NAME'
        }
    }
}}


class TestResponse(requests.Response):
    """Utility class to wrap requests.Response.

    Class used to wrap requests.Response and provide some convenience to
    initialize with a dict.
    """

    def __init__(self, data):
        self._text = None
        super(TestResponse, self).__init__()
        if isinstance(data, dict):
            self.status_code = data.get('status_code', 200)
            headers = data.get('headers')
            if headers:
                self.headers.update(headers)
            # Fake the text attribute to streamline Response creation
            # _content is defined by requests.Response
            self._content = data.get('text')
        else:
            self.status_code = data

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    @property
    def text(self):
        return self.content


class FakeApp(object):
    calls = 0
    """This represents a WSGI app protected by the auth_token middleware."""
    def __call__(self, env, start_response):
        self.calls += 1
        resp = Response()
        resp.environ = env
        return resp(env, start_response)


class S3TokenMiddlewareTestBase(unittest.TestCase):

    TEST_AUTH_URI = 'https://fakehost/identity'
    TEST_URL = '%s/v2.0/s3tokens' % (TEST_AUTH_URI, )
    TEST_DOMAIN_ID = '1'
    TEST_DOMAIN_NAME = 'aDomain'
    TEST_GROUP_ID = uuid.uuid4().hex
    TEST_ROLE_ID = uuid.uuid4().hex
    TEST_TENANT_ID = '1'
    TEST_TENANT_NAME = 'aTenant'
    TEST_TOKEN = 'aToken'
    TEST_TRUST_ID = 'aTrust'
    TEST_USER = 'test'
    TEST_USER_ID = uuid.uuid4().hex

    TEST_ROOT_URL = 'http://127.0.0.1:5000/'

    def setUp(self):
        super(S3TokenMiddlewareTestBase, self).setUp()
        self.logger = fixtures.FakeLogger(level=logging.DEBUG)
        self.logger.setUp()
        self.time_patcher = mock.patch.object(time, 'time', lambda: 1234)
        self.time_patcher.start()

        self.app = FakeApp()
        self.conf = {
            'auth_uri': self.TEST_AUTH_URI,
        }
        self.middleware = s3_token.S3Token(self.app, self.conf)

        self.requests_mock = rm_fixture.Fixture()
        self.requests_mock.setUp()

    def tearDown(self):
        self.requests_mock.cleanUp()
        self.time_patcher.stop()
        self.logger.cleanUp()
        super(S3TokenMiddlewareTestBase, self).tearDown()

    def start_fake_response(self, status, headers):
        self.response_status = int(status.split(' ', 1)[0])
        self.response_headers = dict(headers)


class S3TokenMiddlewareTestGood(S3TokenMiddlewareTestBase):

    def setUp(self):
        super(S3TokenMiddlewareTestGood, self).setUp()

        self.requests_mock.post(self.TEST_URL,
                                status_code=201,
                                json=GOOD_RESPONSE)

    # Ignore the request and pass to the next middleware in the
    # pipeline if no path has been specified.
    def test_no_path_request(self):
        req = Request.blank('/')
        self.middleware(req.environ, self.start_fake_response)
        self.assertEqual(self.response_status, 200)

    # Ignore the request and pass to the next middleware in the
    # pipeline if no Authorization header has been specified
    def test_without_authorization(self):
        req = Request.blank('/v1/AUTH_cfa/c/o')
        self.middleware(req.environ, self.start_fake_response)
        self.assertEqual(self.response_status, 200)

    def test_nukes_auth_headers(self):
        client_env = {
            'HTTP_X_IDENTITY_STATUS': 'Confirmed',
            'HTTP_X_ROLES': 'admin,_member_,swift-user',
            'HTTP_X_TENANT_ID': 'cfa'
        }
        req = Request.blank('/v1/AUTH_cfa/c/o', environ=client_env)
        self.middleware(req.environ, self.start_fake_response)
        self.assertEqual(self.response_status, 200)
        for key in client_env:
            self.assertNotIn(key, req.environ)

    def test_without_auth_storage_token(self):
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.headers['Authorization'] = 'AWS badboy'
        self.middleware(req.environ, self.start_fake_response)
        self.assertEqual(self.response_status, 200)

    def _assert_authorized(self, req, expect_token=True):
        self.assertTrue(req.path.startswith('/v1/AUTH_TENANT_ID'))
        expected_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Roles': 'swift-user,_member_',
            'X-User-Id': 'USER_ID',
            'X-User-Name': 'S3_USER',
            'X-Tenant-Id': 'TENANT_ID',
            'X-Tenant-Name': 'TENANT_NAME',
            'X-Project-Id': 'TENANT_ID',
            'X-Project-Name': 'TENANT_NAME',
            'X-Auth-Token': 'TOKEN_ID',
        }
        for header, value in expected_headers.items():
            if header == 'X-Auth-Token' and not expect_token:
                self.assertNotIn(header, req.headers)
                continue
            self.assertIn(header, req.headers)
            self.assertEqual(value, req.headers[header])
            # WSGI wants native strings for headers
            self.assertIsInstance(req.headers[header], str)
        self.assertEqual(1, self.middleware._app.calls)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_authorized(self):
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        self._assert_authorized(req)

    def test_tolerate_missing_token_id(self):
        resp = copy.deepcopy(GOOD_RESPONSE)
        del resp['access']['token']['id']
        self.requests_mock.post(self.TEST_URL,
                                status_code=201,
                                json=resp)

        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        self._assert_authorized(req, expect_token=False)

    def test_authorized_bytes(self):
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': b'access',
            'signature': b'signature',
            'string_to_sign': b'token',
        }
        req.get_response(self.middleware)
        self.assertTrue(req.path.startswith('/v1/AUTH_TENANT_ID'))
        self.assertEqual(req.headers['X-Auth-Token'], 'TOKEN_ID')

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_authorized_http(self):
        protocol = 'http'
        host = 'fakehost'
        port = 35357
        self.requests_mock.post(
            '%s://%s:%s/v2.0/s3tokens' % (protocol, host, port),
            status_code=201, json=GOOD_RESPONSE)

        self.middleware = (
            s3_token.filter_factory({'auth_protocol': 'http',
                                     'auth_host': host,
                                     'auth_port': port})(self.app))
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        self._assert_authorized(req)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_authorized_trailing_slash(self):
        self.middleware = s3_token.filter_factory({
            'auth_uri': self.TEST_AUTH_URI + '/'})(self.app)
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        self._assert_authorized(req)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_authorization_nova_toconnect(self):
        req = Request.blank('/v1/AUTH_swiftint/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access:FORCED_TENANT_ID',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        path = req.environ['PATH_INFO']
        self.assertTrue(path.startswith('/v1/AUTH_FORCED_TENANT_ID'))

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    @mock.patch.object(requests, 'post')
    def test_insecure(self, MOCK_REQUEST):
        self.middleware = s3_token.filter_factory(
            {'insecure': 'True', 'auth_uri': 'http://example.com'})(self.app)

        text_return_value = json.dumps(GOOD_RESPONSE)
        MOCK_REQUEST.return_value = TestResponse({
            'status_code': 201,
            'text': text_return_value})

        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)

        self.assertTrue(MOCK_REQUEST.called)
        mock_args, mock_kwargs = MOCK_REQUEST.call_args
        self.assertIs(mock_kwargs['verify'], False)

    def test_insecure_option(self):
        # insecure is passed as a string.

        # Some non-secure values.
        true_values = ['true', 'True', '1', 'yes']
        for val in true_values:
            config = {'insecure': val,
                      'certfile': 'false_ind',
                      'auth_uri': 'http://example.com'}
            middleware = s3_token.filter_factory(config)(self.app)
            self.assertIs(False, middleware._verify)

        # Some "secure" values, including unexpected value.
        false_values = ['false', 'False', '0', 'no', 'someweirdvalue']
        for val in false_values:
            config = {'insecure': val,
                      'certfile': 'false_ind',
                      'auth_uri': 'http://example.com'}
            middleware = s3_token.filter_factory(config)(self.app)
            self.assertEqual('false_ind', middleware._verify)

        # Default is secure.
        config = {'certfile': 'false_ind',
                  'auth_uri': 'http://example.com'}
        middleware = s3_token.filter_factory(config)(self.app)
        self.assertIs('false_ind', middleware._verify)

    def test_ipv6_auth_host_option(self):
        config = {}
        ipv6_addr = '::FFFF:129.144.52.38'
        identity_uri = 'https://[::FFFF:129.144.52.38]:35357'

        # Raw IPv6 address should work
        config['auth_host'] = ipv6_addr
        middleware = s3_token.filter_factory(config)(self.app)
        self.assertEqual(identity_uri, middleware._request_uri)

        # ...as should workarounds already in use
        config['auth_host'] = '[%s]' % ipv6_addr
        middleware = s3_token.filter_factory(config)(self.app)
        self.assertEqual(identity_uri, middleware._request_uri)

        # ... with no config, we should get config error
        del config['auth_host']
        with self.assertRaises(ConfigFileError) as cm:
            s3_token.filter_factory(config)(self.app)
        self.assertEqual('Either auth_uri or auth_host required',
                         cm.exception.message)

    @mock.patch.object(requests, 'post')
    def test_http_timeout(self, MOCK_REQUEST):
        self.middleware = s3_token.filter_factory({
            'http_timeout': '2',
            'auth_uri': 'http://example.com',
        })(FakeApp())

        MOCK_REQUEST.return_value = TestResponse({
            'status_code': 201,
            'text': json.dumps(GOOD_RESPONSE)})

        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)

        self.assertTrue(MOCK_REQUEST.called)
        mock_args, mock_kwargs = MOCK_REQUEST.call_args
        self.assertEqual(mock_kwargs['timeout'], 2)

    def test_http_timeout_option(self):
        good_values = ['1', '5.3', '10', '.001']
        for val in good_values:
            middleware = s3_token.filter_factory({
                'http_timeout': val,
                'auth_uri': 'http://example.com',
            })(FakeApp())
            self.assertEqual(float(val), middleware._timeout)

        bad_values = ['1, 4', '-3', '100', 'foo', '0']
        for val in bad_values:
            with self.assertRaises(ValueError) as ctx:
                s3_token.filter_factory({
                    'http_timeout': val,
                    'auth_uri': 'http://example.com',
                })(FakeApp())
            self.assertTrue(ctx.exception.args[0].startswith((
                'invalid literal for float():',
                'could not convert string to float:',
                'http_timeout must be between 0 and 60 seconds',
            )), 'Unexpected error message: %s' % ctx.exception)

        # default is 10 seconds
        middleware = s3_token.filter_factory({
            'auth_uri': 'http://example.com'})(FakeApp())
        self.assertEqual(10, middleware._timeout)

    def test_unicode_path(self):
        url = u'/v1/AUTH_cfa/c/euro\u20ac'.encode('utf8')
        req = Request.blank(urllib.parse.quote(url))
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        req.get_response(self.middleware)
        self._assert_authorized(req)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})


class S3TokenMiddlewareTestBad(S3TokenMiddlewareTestBase):
    def test_unauthorized_token(self):
        ret = {"error":
               {"message": "EC2 access key not found.",
                "code": 401,
                "title": "Unauthorized"}}
        self.requests_mock.post(self.TEST_URL, status_code=403, json=ret)
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        resp = req.get_response(self.middleware)
        s3_denied_req = self.middleware._deny_request('AccessDenied')
        self.assertEqual(resp.body, s3_denied_req.body)
        self.assertEqual(
            resp.status_int,  # pylint: disable-msg=E1101
            s3_denied_req.status_int)  # pylint: disable-msg=E1101
        self.assertEqual(0, self.middleware._app.calls)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_no_s3_creds(self):
        req = Request.blank('/v1/AUTH_cfa/c/o')
        resp = req.get_response(self.middleware)
        self.assertEqual(resp.status_int, 200)  # pylint: disable-msg=E1101
        self.assertEqual(1, self.middleware._app.calls)

    def test_fail_to_connect_to_keystone(self):
        with mock.patch.object(self.middleware, '_json_request') as o:
            s3_invalid_resp = self.middleware._deny_request('InvalidURI')
            o.side_effect = s3_invalid_resp

            req = Request.blank('/v1/AUTH_cfa/c/o')
            req.environ['swift3.auth_details'] = {
                'access_key': u'access',
                'signature': u'signature',
                'string_to_sign': u'token',
            }
            resp = req.get_response(self.middleware)
            self.assertEqual(resp.body, s3_invalid_resp.body)
            self.assertEqual(
                resp.status_int,  # pylint: disable-msg=E1101
                s3_invalid_resp.status_int)  # pylint: disable-msg=E1101
            self.assertEqual(0, self.middleware._app.calls)

    def _test_bad_reply(self, response_body):
        self.requests_mock.post(self.TEST_URL,
                                status_code=201,
                                text=response_body)

        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        resp = req.get_response(self.middleware)
        s3_invalid_resp = self.middleware._deny_request('InvalidURI')
        self.assertEqual(resp.body, s3_invalid_resp.body)
        self.assertEqual(
            resp.status_int,  # pylint: disable-msg=E1101
            s3_invalid_resp.status_int)  # pylint: disable-msg=E1101
        self.assertEqual(0, self.middleware._app.calls)

    def test_bad_reply_not_json(self):
        self._test_bad_reply('<badreply>')

    def _test_bad_reply_missing_parts(self, *parts):
        resp = copy.deepcopy(GOOD_RESPONSE)
        part_dict = resp
        for part in parts[:-1]:
            part_dict = part_dict[part]
        del part_dict[parts[-1]]
        self._test_bad_reply(json.dumps(resp))

    def test_bad_reply_missing_token_dict(self):
        self._test_bad_reply_missing_parts('access', 'token')

    def test_bad_reply_missing_user_dict(self):
        self._test_bad_reply_missing_parts('access', 'user')

    def test_bad_reply_missing_user_roles(self):
        self._test_bad_reply_missing_parts('access', 'user', 'roles')

    def test_bad_reply_missing_user_name(self):
        self._test_bad_reply_missing_parts('access', 'user', 'name')

    def test_bad_reply_missing_user_id(self):
        self._test_bad_reply_missing_parts('access', 'user', 'id')

    def test_bad_reply_missing_tenant_dict(self):
        self._test_bad_reply_missing_parts('access', 'token', 'tenant')

    def test_bad_reply_missing_tenant_id(self):
        self._test_bad_reply_missing_parts('access', 'token', 'tenant', 'id')

    def test_bad_reply_missing_tenant_name(self):
        self._test_bad_reply_missing_parts('access', 'token', 'tenant', 'name')

    def test_bad_reply_valid_but_bad_json(self):
        self._test_bad_reply('{}')
        self._test_bad_reply('[]')
        self._test_bad_reply('null')
        self._test_bad_reply('"foo"')
        self._test_bad_reply('1')
        self._test_bad_reply('true')


class S3TokenMiddlewareTestDeferredAuth(S3TokenMiddlewareTestBase):
    def setUp(self):
        super(S3TokenMiddlewareTestDeferredAuth, self).setUp()
        self.conf['delay_auth_decision'] = 'yes'
        self.middleware = s3_token.S3Token(FakeApp(), self.conf)

    def test_unauthorized_token(self):
        ret = {"error":
               {"message": "EC2 access key not found.",
                "code": 401,
                "title": "Unauthorized"}}
        self.requests_mock.post(self.TEST_URL, status_code=403, json=ret)
        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        resp = req.get_response(self.middleware)
        self.assertEqual(
            resp.status_int,  # pylint: disable-msg=E1101
            200)
        self.assertNotIn('X-Auth-Token', req.headers)
        self.assertEqual(1, self.middleware._app.calls)

        self.assertEqual(1, self.requests_mock.call_count)
        request_call = self.requests_mock.request_history[0]
        self.assertEqual(json.loads(request_call.body), {'credentials': {
            'access': 'access',
            'signature': 'signature',
            'token': base64.urlsafe_b64encode(b'token').decode('ascii')}})

    def test_fail_to_connect_to_keystone(self):
        with mock.patch.object(self.middleware, '_json_request') as o:
            o.side_effect = self.middleware._deny_request('InvalidURI')

            req = Request.blank('/v1/AUTH_cfa/c/o')
            req.environ['swift3.auth_details'] = {
                'access_key': u'access',
                'signature': u'signature',
                'string_to_sign': u'token',
            }
            resp = req.get_response(self.middleware)
            self.assertEqual(
                resp.status_int,  # pylint: disable-msg=E1101
                200)
        self.assertNotIn('X-Auth-Token', req.headers)
        self.assertEqual(1, self.middleware._app.calls)

    def test_bad_reply(self):
        self.requests_mock.post(self.TEST_URL,
                                status_code=201,
                                text="<badreply>")

        req = Request.blank('/v1/AUTH_cfa/c/o')
        req.environ['swift3.auth_details'] = {
            'access_key': u'access',
            'signature': u'signature',
            'string_to_sign': u'token',
        }
        resp = req.get_response(self.middleware)
        self.assertEqual(
            resp.status_int,  # pylint: disable-msg=E1101
            200)
        self.assertNotIn('X-Auth-Token', req.headers)
        self.assertEqual(1, self.middleware._app.calls)
