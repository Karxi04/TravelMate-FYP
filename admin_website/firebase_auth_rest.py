import os
import requests
IDENTITY_BASE="https://identitytoolkit.googleapis.com/v1/accounts"; TOKEN_BASE="https://securetoken.googleapis.com/v1/token"
def _key():
    key=os.getenv('FIREBASE_WEB_API_KEY','').strip()
    if not key: raise RuntimeError('FIREBASE_WEB_API_KEY is not configured')
    return key

def createUserAccount(email,password):
    r=requests.post(f'{IDENTITY_BASE}:signUp',params={'key':_key()},json={'email':email,'password':password,'returnSecureToken':True},timeout=30); return r.json(),r.status_code

def authenticateCredentials(email,password):
    r=requests.post(f'{IDENTITY_BASE}:signInWithPassword',params={'key':_key()},json={'email':email,'password':password,'returnSecureToken':True},timeout=30); return r.json(),r.status_code

def sendPasswordResetEmail(email):
    r=requests.post(f'{IDENTITY_BASE}:sendOobCode',params={'key':_key()},json={'requestType':'PASSWORD_RESET','email':email},timeout=30); return r.json(),r.status_code

def signOutUser(sessionObject):
    sessionObject.clear(); return True

def refresh_id_token(refresh_token):
    r=requests.post(TOKEN_BASE,params={'key':_key()},data={'grant_type':'refresh_token','refresh_token':refresh_token},timeout=30); return r.json(),r.status_code

# aliases retained for existing integrations
sign_in=authenticateCredentials
sign_up=createUserAccount
send_password_reset=sendPasswordResetEmail
