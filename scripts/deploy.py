"""Update only the image of the existing Stars Compose service."""
import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

IMAGE = 'ghcr.io/cahangeorge/github-stars-manager-official-fullstack'
PREVIOUS_IMAGE = 'ghcr.io/cahangeorge/github-stars-manager-fullstack'
SERVICE = 'vofdyllbdhlhpztexwtoqwss'
COMPONENT = 'xruvvuahqotl2ksswt7wl1ko'
HEALTH = 'https://stars.omnestack.com/api/health'

class Halt(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Halt('HTTP redirect refused')

def request(method, url, body=None, token=None, missing_spa=False):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'stars-official-update/1'}
    if token: headers['Authorization'] = 'Bearer ' + token
    data = None if body is None else json.dumps(body).encode()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            raw = response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: raise Halt('Response too large')
            if missing_spa and response.headers.get('Content-Type','').startswith('text/html') and raw.lstrip().lower().startswith(b'<!doctype html>'):
                return None  # Official SPA fallback when the static marker is absent.
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise Halt(method+' HTTP '+str(error.code)+'; response body suppressed') from None
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        raise Halt(method+' network operation failed; details suppressed') from None
    except ValueError:
        raise Halt(method+' returned invalid JSON; body suppressed') from None

def image(value, previous=False):
    package = '(?:'+re.escape(IMAGE)+'|'+re.escape(PREVIOUS_IMAGE)+')' if previous else re.escape(IMAGE)
    if not isinstance(value,str) or not re.fullmatch(package+r'@sha256:[a-f0-9]{64}',value):
        raise Halt('Expected fixed package and immutable image digest')
    return value

def component(service):
    if service.get('uuid') != SERVICE: raise Halt('Wrong service')
    selected = [a for a in service.get('applications',[]) if a.get('uuid')==COMPONENT]
    if len(selected)!=1: raise Halt('Wrong component')
    return selected[0]

def replace_image(raw, old, new):
    image(old,previous=True); image(new)
    if not isinstance(raw,str) or raw.count(old)!=1: raise Halt('Ambiguous saved Compose')
    lines = re.findall(r'(?m)^\s*image\s*:.*$',raw)
    scalar = '(?:'+re.escape(old)+"|'"+re.escape(old)+"'|\""+re.escape(old)+'")'
    if len(lines)!=1 or not re.fullmatch(r'\s*image\s*:\s*'+scalar+r'\s*',lines[0]):
        raise Halt('Unexpected image scalar')
    return raw.replace(old,new,1)

def deploy(desired, api, health, sleep=time.sleep, identity=None):
    image(desired)
    if identity is None: raise Halt('Runtime identity probe required')
    path = '/services/'+SERVICE
    live = api('GET',path)
    app = component(live)
    old = image(app.get('image'),previous=True)
    status = app.get('status')
    if old==desired and status=='running:healthy':
        if not health(): raise Halt('Unchanged healthy image; public probe failed, no mutation')
        if identity():
            print('Already serving the official commit; no deployment changes')
            return
    if status in ('running:healthy','running:unhealthy'): action='restart'
    elif status in ('exited','exited:unhealthy'): action='start'
    else: raise Halt('Service is transitional or unknown; no mutation')
    raw = live.get('docker_compose_raw')
    updated = replace_image(raw,old,desired)
    fresh = api('GET',path)
    if fresh.get('docker_compose_raw')!=raw or component(fresh).get('image')!=old or component(fresh).get('status')!=status:
        raise Halt('Service changed during preflight; no mutation')
    if old!=desired:
        api('PATCH',path,{'docker_compose_raw':base64.b64encode(updated.encode()).decode(),'instant_deploy':False})
    api('POST',path+'/'+action,{'latest':True})
    for _ in range(60):
        sleep(10)
        current=component(api('GET',path))
        if current.get('image')==desired and current.get('status')=='running:healthy' and health() and identity():
            print('Official image deployed; Coolify and public API healthy')
            return
    raise Halt('Deployment health timeout; no automatic rollback')

def main():
    base = os.environ.get('COOLIFY_API_URL','').rstrip('/')
    url = urllib.parse.urlsplit(base)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path!='/api/v1':
        raise Halt('Expected HTTPS Coolify API base ending in /api/v1')
    token=os.environ.get('COOLIFY_TOKEN')
    if not token: raise Halt('Missing Coolify token')
    sha=os.environ.get('SOURCE_SHA','')
    if not re.fullmatch(r'[a-f0-9]{40}',sha): raise Halt('Invalid official commit SHA')
    def api(method,path,body=None): return request(method,base+path,body,token)
    def health():
        try: return request('GET',HEALTH).get('status')=='ok'
        except Halt: return False
    def identity():
        url='https://stars.omnestack.com/__official_'+sha+'.json'
        try:return request('GET',url,missing_spa=True)=={'upstream_sha':sha}
        except Halt as error:
            if str(error).startswith('GET HTTP 404;'):return False
            raise
    deploy(os.environ.get('DESIRED_IMAGE'),api,health,identity=identity)

if __name__=='__main__':
    try: main()
    except Halt as error:
        print('HALT: '+str(error),file=sys.stderr)
        sys.exit(1)
