import unittest
from unittest.mock import patch
import deploy

OLD = deploy.IMAGE + '@sha256:' + 'a' * 64
NEW = deploy.IMAGE + '@sha256:' + 'b' * 64
RAW = 'services:\n  stars:\n    image: "' + OLD + '"\n    volumes:\n      - data:/app/data\n    environment:\n      API_SECRET: ${API_SECRET}\n'

def service(image=OLD, raw=RAW, status='running:healthy'):
    return {'uuid': deploy.SERVICE, 'docker_compose_raw': raw,
            'applications': [{'uuid': deploy.COMPONENT, 'image': image, 'status': status}]}

class DeployTests(unittest.TestCase):
    def test_only_image_changes(self):
        self.assertEqual(deploy.replace_image(RAW, OLD, NEW), RAW.replace(OLD, NEW))

    def test_ambiguous_compose_rejected(self):
        for raw in (RAW + '  other:\n    image: ' + OLD + '\n', RAW.replace(OLD, '${IMAGE}'), ''):
            with self.assertRaises(deploy.Halt): deploy.replace_image(raw, OLD, NEW)

    def test_wrong_image_rejected(self):
        with self.assertRaises(deploy.Halt): deploy.image('ghcr.io/other/project@sha256:' + 'b'*64)

    def test_already_deployed_does_not_write(self):
        calls=[]
        def api(method, path, body=None):
            calls.append(method); return service(NEW, RAW.replace(OLD, NEW))
        deploy.deploy(NEW, api, lambda: True, lambda _: None)
        self.assertEqual(calls, ['GET'])

    def test_drift_stops_before_write(self):
        calls=[]
        def api(method, path, body=None):
            calls.append(method)
            return service(raw=RAW if len(calls)==1 else RAW+'# owner changed config\n')
        with self.assertRaises(deploy.Halt): deploy.deploy(NEW, api, lambda: True, lambda _: None)
        self.assertEqual(calls, ['GET','GET'])

    def test_transitional_status_stops_before_write(self):
        calls=[]
        def api(method,path,body=None):
            calls.append(method);return service(status='starting')
        with self.assertRaises(deploy.Halt): deploy.deploy(NEW,api,lambda:True,lambda _:None)
        self.assertEqual(calls,['GET'])

    def test_restart_patches_without_instant_deploy_and_pulls(self):
        calls=[]
        def api(method,path,body=None):
            calls.append((method,path,body))
            if method=='GET':return service() if len(calls)<5 else service(NEW,RAW.replace(OLD,NEW))
            return {}
        deploy.deploy(NEW,api,lambda:True,lambda _:None)
        self.assertEqual([x[0] for x in calls],['GET','GET','PATCH','POST','GET'])
        self.assertFalse(calls[2][2]['instant_deploy'])
        self.assertTrue(calls[3][1].endswith('/restart'))
        self.assertEqual(calls[3][2],{'latest':True})

    def test_timeout_has_no_rollback(self):
        calls=[]
        def api(method,path,body=None):calls.append(method);return service()
        with self.assertRaises(deploy.Halt):deploy.deploy(NEW,api,lambda:False,lambda _:None)
        self.assertEqual(calls.count('PATCH'),1)
        self.assertEqual(calls.count('POST'),1)

if __name__=='__main__':unittest.main()
