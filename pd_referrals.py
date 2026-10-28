"""Private Drive referral API: same ledger as the Telegram bot."""
import re
import urllib.parse
from functools import lru_cache
import Euro_Baltic_Transfer as core

@lru_cache(maxsize=1)
def bot_username():
    return core.bot.get_me().username

def summary(uid):
    core.referral_initialize()
    core.referral_touch(uid)
    core.referral_sync(uid)
    with core.db(core.USERS_DB) as c:
        member=c.execute('SELECT code FROM ref_members WHERE uid=?',(uid,)).fetchone()
        invited=c.execute('SELECT COUNT(*) FROM ref_members WHERE inviter=?',(uid,)).fetchone()[0]
        earned=c.execute('SELECT COALESCE(SUM(points),0) FROM ref_rewards WHERE inviter=?',(uid,)).fetchone()[0]
        promo=c.execute('SELECT COALESCE(SUM(points),0) FROM ref_redemptions WHERE uid=?',(uid,)).fetchone()[0]
    url='https://t.me/'+bot_username()+'?start=ref_'+member['code']
    share='https://t.me/share/url?'+urllib.parse.urlencode({'url':url,'text':'PRIVATE DRIVE — индивидуальные поездки по Литве и Европе. Откройте бота по моей ссылке.'})
    return dict(invited=invited,earned_points=earned,promo_points=promo,balance=earned+promo,referral_url=url,share_url=share)

def redeem(uid,raw):
    if not isinstance(raw,str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,32}',raw.strip()):
        raise ValueError('Введите промокод: 3–32 латинские буквы, цифры, _ или -')
    code=raw.strip().upper()
    core.referral_initialize()
    core.referral_touch(uid)
    with core.db(core.USERS_DB) as c:
        c.execute('BEGIN IMMEDIATE')
        p=c.execute('SELECT * FROM ref_promos WHERE code=? AND active=1',(code,)).fetchone()
        if c.execute('SELECT 1 FROM ref_redemptions WHERE uid=? AND code=?',(uid,code)).fetchone():
            raise ValueError('Этот промокод уже использован вами')
        count=c.execute('SELECT COUNT(*) FROM ref_redemptions WHERE code=?',(code,)).fetchone()[0]
        if not p or count>=p['max_uses']:
            raise ValueError('Промокод недействителен или лимит исчерпан')
        c.execute('INSERT INTO ref_redemptions VALUES(?,?,?,?)',(uid,code,p['points'],core.now().isoformat()))
    return dict(ok=True,points=p['points'],message='Начислено '+str(p['points'])+' бонусных баллов')

def register(app,auth):
    from flask import request,jsonify
    @app.get('/api/bonus')
    def pd_bonus_summary():
        uid,_=auth()
        return jsonify(summary(uid))
    @app.post('/api/bonus/promo')
    def pd_bonus_redeem():
        uid,_=auth()
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):
            raise ValueError('Некорректный запрос')
        return jsonify(redeem(uid,data.get('code')))
