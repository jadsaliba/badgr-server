import os
from urlparse import urlparse, parse_qs

from django.shortcuts import reverse
from django.test import override_settings
from django.test.client import RequestFactory

from badgrsocialauth.models import Saml2Configuration, Saml2Account
from badgrsocialauth.views import auto_provision, saml2_client_for
from badgrsocialauth.utils import set_session_authcode

from badgeuser.models import CachedEmailAddress, BadgeUser

from mainsite.models import AccessTokenProxy, BadgrApp
from mainsite.tests import BadgrTestCase, SetupUserHelper
from mainsite import TOP_DIR

class SAML2Tests(BadgrTestCase):
    def setUp(self):
        super(SAML2Tests, self).setUp()
        self.test_files_path = os.path.join(TOP_DIR, 'apps', 'badgrsocialauth', 'testfiles')
        self.ipd_metadata_path = os.path.join(self.test_files_path, 'idp-test-metadata.txt')
        with open(self.ipd_metadata_path, 'r') as f:
            metadata_xml = f.read()
        self.config = Saml2Configuration.objects.create(
            metadata_conf_url="http://example.com", slug="saml2.test", cached_metadata=metadata_xml
        )
        self.ipd_cert_path = os.path.join(self.test_files_path, 'idp-test-cert.pem')
        self.ipd_key_path = os.path.join(self.test_files_path, 'idp-test-key.pem')

        self.badgr_app = BadgrApp.objects.create(
            ui_login_redirect="https://example.com", ui_signup_failure_redirect='https://example.com/fail'
        )

    def create_signed_auth_request_saml2Configuration(self, idp_metadata):
        return Saml2Configuration.objects.create(
            metadata_conf_url="http://example.com",
            cached_metadata=idp_metadata,
            slug='saml2.authn',
            use_signed_authn_request=True
        )

    def test_signed_authn_request_option_creates_signed_metadata(self):
        with override_settings(
                SAML_KEY_FILE=self.ipd_key_path,
                SAML_CERT_FILE=self.ipd_cert_path):
            with open(self.ipd_metadata_path, 'r') as f:
                idp_metadata = f.read()
                authn_request = self.create_signed_auth_request_saml2Configuration(idp_metadata)
                saml_client, config = saml2_client_for(authn_request.slug)
                self.assertTrue(saml_client.authn_requests_signed)
                self.assertNotEqual(saml_client.sec.sec_backend, None)

    def test_signed_authn_request_option_returns_self_posting_form_populated_with_signed_metadata(self):
        with override_settings(
                SAML_KEY_FILE=self.ipd_key_path,
                SAML_CERT_FILE=self.ipd_cert_path):
            with open(self.ipd_metadata_path, 'r') as f:
                idp_metadata = f.read()
                authn_request = self.create_signed_auth_request_saml2Configuration(idp_metadata)
                url = '/account/sociallogin?provider=' + authn_request.slug
                redirect_url = '/account/saml2/' + authn_request.slug + '/'
                response = self.client.get(url, follow=True)
                intermediate_url, intermediate_url_status = response.redirect_chain[0]

                # login redirect to saml2 login
                self.assertEqual(intermediate_url, redirect_url)
                self.assertEqual(intermediate_url_status, 302)
                # self populated form generated with metadata file from self.ipd_metadata_path
                self.assertEqual(response.status_code, 200)
                # changing attribute location of element md:SingleSignOnService necessitates updating this value
                self.assertIsNot(
                    response.content.find('<form action="https://example.com/saml2/idp/SSOService.php" method="post">'), -1)
                self.assertIsNot(
                    response.content.find('<input type="hidden" name="SAMLRequest" value="'), -1)

    def test_create_saml2_client(self):
        Saml2Configuration.objects.create(metadata_conf_url="http://example.com", cached_metadata="<xml></xml>",  slug="saml2.test2")
        client = saml2_client_for("saml2.test2")
        self.assertNotEqual(client, None)

    def test_oauth_to_saml2_redirection_flow(self):
        resp = self.client.get('/account/sociallogin?provider=' + self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/account/saml2/{}/'.format(self.config.slug))

    def test_login_with_registered_saml2_account(self):
        email = "test123@example.com"
        first_name = "firsty"
        last_name = "lastington"
        new_user = BadgeUser.objects.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        # Auto verify emails
        email = CachedEmailAddress.objects.get(email=email)
        email.verified = True
        email.save()
        Saml2Account.objects.create(config=self.config, user=new_user, uuid=email)
        badgr_app = BadgrApp.objects.create(ui_login_redirect="example.com", cors='example.com')
        resp = auto_provision(None, email, first_name, last_name, badgr_app, self.config, self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)

    def test_login_with_unregistered_saml2_account(self):
        email = "test456@example.com"
        first_name = "firsty"
        last_name = "lastington"
        badgr_app = self.badgr_app
        resp = auto_provision(None, email, first_name, last_name, badgr_app, self.config, self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)

    def test_saml2_login_with_conflicts(self):
        email = "test8679@example.com"
        email2 = "test234425@example.com"
        first_name = "firsty"
        last_name = "lastington"
        idp_name = self.config.slug
        badgr_app = self.badgr_app

        # email does not exist
        resp = auto_provision(
            None, "different425@example.com", first_name, last_name, badgr_app, self.config, self.config.slug
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)
        self.assertEqual(Saml2Account.objects.all().count(), 1)
        email_address = CachedEmailAddress.objects.get(email='different425@example.com')
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

        # email exists, but is unverified
        BadgeUser.objects.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
            send_confirmation=False
        )
        resp = auto_provision(None, email, first_name, last_name, badgr_app, self.config, self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)
        email_address = CachedEmailAddress.objects.get(email=email)
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

        # Can auto provision again
        resp = auto_provision(None, email, first_name, last_name, badgr_app, self.config, self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)

        # email exists, but is verified
        BadgeUser.objects.create(
            email=email2,
            first_name=first_name,
            last_name=last_name,
            send_confirmation=False
        )
        cachedemail = CachedEmailAddress.objects.get(email=email2)
        cachedemail.verified = True
        cachedemail.save()
        saml_account_count = Saml2Account.objects.count()
        resp = auto_provision(None, email2, first_name, last_name, badgr_app, self.config, self.config.slug)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authError", resp.url)
        self.assertIn(self.config.slug, resp.url)
        self.assertEqual(saml_account_count, Saml2Account.objects.count(), "A Saml2Account must not have been created.")

    def test_add_samlaccount_to_existing_user(self):
        # email exists, but is verified
        email = 'exampleuser@example.com'
        test_user = self.setup_user(
            email=email,
            token_scope='rw:profile rw:issuer rw:backpack'
        )

        preflight_response = self.client.get(
            reverse('v2_api_user_socialaccount_connect') + '?provider={}'.format(self.config.slug)
        )
        self.assertEqual(preflight_response.status_code, 200)
        location = urlparse(preflight_response.data['result']['url'])
        authcode = parse_qs(location.query)['authCode'][0]
        location = '?'.join([location.path, location.query])

        # the location now includes an auth code
        self.client.logout()
        response = self.client.get(location)
        self.assertEqual(response.status_code, 302)
        location = response._headers['location'][1]

        response = self.client.get(location)
        self.assertEqual(response.status_code, 302)

        # Can auto provision again
        rf = RequestFactory()
        fake_request = rf.post(
            reverse('assertion_consumer_service', kwargs={'idp_name': self.config.slug}),
            {'saml_assertion': 'very fake'}
        )
        fake_request.session = dict()
        set_session_authcode(fake_request, authcode)

        resp = auto_provision(
            fake_request, email, test_user.first_name, test_user.last_name, self.badgr_app, self.config, self.config.slug
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("authToken", resp.url)
        account = Saml2Account.objects.get(user=test_user)
