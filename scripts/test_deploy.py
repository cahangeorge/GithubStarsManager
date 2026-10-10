import unittest
from unittest.mock import patch, MagicMock
import deploy

OLD = deploy.IMAGE + '@sha256:' + 'a' * 64
NEW = deploy.IMAGE + '@sha256:' + 'b' * 64
RAW = 'services:\n  stars:\n    image: "' + OLD + '"\n    volumes:\n      - data:/app/data\n    environment:\n      API_SECRET: ${API_SECRET}\n'

def service(image=OLD, raw=RAW, status='running:healthy'):
    return {'uuid': deploy.SERVICE, 'docker_compose_raw': raw,
            'applications': [{'uuid': deploy.COMPONENT, 'image': image, 'status': status}]}

class DeployTests(unittest.TestCase):
    def test_missing_marker_official_spa_shell_is_absent_not_network_failure(self):
        response=MagicMock()
        response.headers={'Content-Type':'text/html; charset=utf-8'}
        response.read.return_value=b'<!doctype html>\n<html><head></head><body><div id="root"></div></body></html>'
        response.__enter__.return_value=response
        with patch('deploy.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertIsNone(deploy.request('GET','https://stars.omnestack.com/__official_test.json',missing_spa=True))
            with self.assertRaises(deploy.Halt):deploy.request('GET','https://stars.omnestack.com/api/health')

    def test_only_image_changes(self):
        self.assertEqual(deploy.replace_image(RAW, OLD, NEW), RAW.replace(OLD, NEW))

    def test_ambiguous_compose_rejected(self):
        for raw in (RAW + '  other:\n    image: ' + OLD + '\n', RAW.replace(OLD, '${IMAGE}'), ''):
            with self.assertRaises(deploy.Halt): deploy.replace_image(raw, OLD, NEW)

    def test_wrong_image_rejected(self):
        with self.assertRaises(deploy.Halt): deploy.image('ghcr.io/other/project@sha256:' + 'b'*64)

    def test_initial_switch_accepts_only_the_fixed_legacy_package(self):
        old=deploy.PREVIOUS_IMAGE+'@sha256:'+'a'*64
        raw=RAW.replace(OLD,old)
        self.assertEqual(deploy.replace_image(raw,old,NEW),raw.replace(old,NEW))
        with self.assertRaises(deploy.Halt):deploy.image(old)

    def test_already_deployed_does_not_write(self):
        calls=[]
        def api(method, path, body=None):
            calls.append(method); return service(NEW, RAW.replace(OLD, NEW))
        deploy.deploy(NEW, api, lambda: True, lambda _: None, identity=lambda: True)
        self.assertEqual(calls, ['GET'])

    def test_drift_stops_before_write(self):
        calls=[]
        def api(method, path, body=None):
            calls.append(method)
            return service(raw=RAW if len(calls)==1 else RAW+'# owner changed config\n')
        with self.assertRaises(deploy.Halt): deploy.deploy(NEW, api, lambda: True, lambda _: None, identity=lambda: True)
        self.assertEqual(calls, ['GET','GET'])

    def test_public_probe_failure_does_not_restart_unchanged_image(self):
        calls=[]
        def api(method,path,body=None):
            calls.append(method);return service(NEW,RAW.replace(OLD,NEW))
        with self.assertRaises(deploy.Halt):deploy.deploy(NEW,api,lambda:False,lambda _:None, identity=lambda:True)
        self.assertEqual(calls,['GET'])

    def test_transitional_status_stops_before_write(self):
        calls=[]
        def api(method,path,body=None):
            calls.append(method);return service(status='starting')
        with self.assertRaises(deploy.Halt): deploy.deploy(NEW,api,lambda:True,lambda _:None, identity=lambda:True)
        self.assertEqual(calls,['GET'])

    def test_restart_patches_without_instant_deploy_and_pulls(self):
        calls=[]
        def api(method,path,body=None):
            calls.append((method,path,body))
            if method=='GET':return service() if len(calls)<5 else service(NEW,RAW.replace(OLD,NEW))
            return {}
        deploy.deploy(NEW,api,lambda:True,lambda _:None, identity=lambda:True)
        self.assertEqual([x[0] for x in calls],['GET','GET','PATCH','POST','GET'])
        self.assertFalse(calls[2][2]['instant_deploy'])
        self.assertTrue(calls[3][1].endswith('/restart'))
        self.assertEqual(calls[3][2],{'latest':True})

    def test_timeout_has_no_rollback(self):
        calls=[]
        def api(method,path,body=None):calls.append(method);return service()
        with self.assertRaises(deploy.Halt):deploy.deploy(NEW,api,lambda:False,lambda _:None, identity=lambda:True)
        self.assertEqual(calls.count('PATCH'),1)
        self.assertEqual(calls.count('POST'),1)

    def test_patch_success_restart_failure_is_retried_until_runtime_matches(self):
        state={'image':OLD,'raw':RAW,'runtime_matches':False,'post_count':0}
        calls=[]
        def api(method,path,body=None):
            calls.append(method)
            if method=='PATCH':
                state['image']=NEW;state['raw']=RAW.replace(OLD,NEW)
            if method=='POST':
                state['post_count']+=1
                if state['post_count']==1:raise deploy.Halt('POST network operation failed')
                state['runtime_matches']=True
            return service(state['image'],state['raw'])
        def identity():return state['runtime_matches']
        with self.assertRaises(deploy.Halt):deploy.deploy(NEW,api,lambda:True,lambda _:None,identity=identity)
        self.assertEqual(calls,['GET','GET','PATCH','POST'])
        calls.clear()
        deploy.deploy(NEW,api,lambda:True,lambda _:None,identity=identity)
        self.assertEqual(calls,['GET','GET','POST','GET'])
        calls.clear()
        deploy.deploy(NEW,api,lambda:True,lambda _:None,identity=identity)
        self.assertEqual(calls,['GET'])

if __name__=='__main__':unittest.main()
