"""Smoke tests for login, independent judge scores, admin-only timer and CSV.
Run with: pytest -q
"""
from __future__ import annotations

import importlib
import os

import pytest

@pytest.fixture()
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'test.db'))
    monkeypatch.setenv('SECRET_KEY', 'this-key-exists-only-for-automated-tests')
    monkeypatch.setenv('ADMIN_USERNAME', 'coordenacao')
    monkeypatch.setenv('ADMIN_PASSWORD', 'senha_de_teste_adequada_123!')
    monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.delenv('RENDER_EXTERNAL_HOSTNAME', raising=False)
    import sys
    sys.modules.pop('app', None)
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    module = importlib.import_module('app')
    module.app.config.update(TESTING=True)
    yield module
    with module.app.app_context():
        module.db.session.remove()
    sys.modules.pop('app', None)


def token(client):
    with client.session_transaction() as sess:
        return sess['csrf_token']


def login(client, user, password):
    client.get('/login')
    return client.post('/login', data={'csrf_token': token(client), 'username': user, 'password': password}, follow_redirects=True)


def test_admin_and_teams_created(setup_app):
    m = setup_app
    with m.app.app_context():
        assert m.Team.query.count() == 9
        assert m.Timer.query.count() == 9
        assert m.User.query.filter_by(role='admin').count() == 1


def test_admin_timer_and_judge_can_evaluate(setup_app):
    m = setup_app
    admin = m.app.test_client()
    assert login(admin, 'coordenacao', 'senha_de_teste_adequada_123!').status_code == 200
    response = admin.post('/admin/judges', data={'csrf_token': token(admin), 'username': 'juiz01', 'display_name': 'Avaliador Um'})
    assert response.status_code == 200
    import re
    password = re.search(r'<strong id="new-password">([^<]+)</strong>', response.get_data(as_text=True)).group(1)
    judge = m.app.test_client()
    assert login(judge,'juiz01',password).status_code == 200
    assert judge.post('/admin/timers/1/start',data={'csrf_token':token(judge)}).status_code == 403
    assert admin.post('/admin/timers/1/start', data={'csrf_token': token(admin)}).status_code == 302
    t = judge.get('/api/state').get_json()['timers']['1']
    assert t['status'] == 'running' and t['elapsed'] == 0
    data = {'csrf_token':token(judge), 'c1':'5','c2':'5','c3':'4',
            'available':'2', 'used':'1', 'notes':'Tudo executado corretamente na IA Box',
            'A1':'correto','A2':'correto','A3':'correto','A4':'correto',
            'D1':'alerta','D2':'alerta'}
    assert judge.post('/evaluate/1', data=data).status_code == 302
    with m.app.app_context():
        e=m.Evaluation.query.filter_by(team_id=1).one()
        assert e.total == 14 and e.cameras_used == 1
    assert 'OutBox' in judge.get('/dashboard').get_data(as_text=True)
    csv_response = admin.get('/admin/export.csv')
    assert csv_response.status_code == 200 and b'juiz01' in csv_response.data
    assert judge.get('/admin/export.csv').status_code == 403


def test_judge_csrf_and_observation_validation(setup_app):
    m = setup_app
    admin = m.app.test_client()
    login(admin,'coordenacao','senha_de_teste_adequada_123!')
    assert admin.post('/admin/timers/1/start',data={}).status_code == 400
    assert admin.post('/admin/timers/1/reset',data={'csrf_token':token(admin), 'reason':'curto'}).status_code == 302
    with m.app.app_context():
        assert m.Timer.query.get(1).status == 'idle'
