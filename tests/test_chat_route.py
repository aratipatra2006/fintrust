"""Flask HTTP contract tests, with mocked database and provider (no real secrets)."""
import os
from unittest.mock import Mock, patch
import pytest
flask = pytest.importorskip('flask')
pytest.importorskip('psycopg')
os.environ.setdefault('DATABASE_URL', 'postgresql://localhost/unused')
from routes import chatbot
from services.gemini_service import ProviderError
from utils.runtime_guard import install_runtime_guard

@pytest.fixture
def client():
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-only-not-for-production')
    install_runtime_guard(app)
    app.register_blueprint(chatbot.chat_bp)
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 98765
        yield c
    chatbot.conversation_memory.pop(98765, None)

def test_bad_input(client):
    assert client.post('/chat', json={'message': 123}).status_code == 400

def test_greeting_without_db(client):
    with patch.object(chatbot, 'get_db', side_effect=AssertionError):
        response = client.post('/chat', json={'message':'hello'})
        assert response.status_code == 200
        assert b'event:done' in response.data
        assert "font-src 'self' https://fonts.gstatic.com" in response.headers['Content-Security-Policy']

def test_database_failure(client):
    with patch.object(chatbot, 'get_db', side_effect=RuntimeError):
        response = client.post('/chat', json={'message':'Explain compound interest'})
    assert response.status_code == 503
    assert response.json['error'] == 'database_unavailable'

@pytest.mark.parametrize('code,status', [('provider_configuration',503),('provider_timeout',504),('provider_response',502)])
def test_provider_failure_before_stream(client, code, status):
    def fail(*args, **kwargs):
        raise ProviderError(code,status)
        yield
    with patch.object(chatbot,'get_db',return_value=Mock()), patch.object(chatbot,'_fetch_full_metrics',return_value={}), patch.object(chatbot,'gemini_stream_chat',side_effect=fail):
        response=client.post('/chat',json={'message':'Explain compound interest'})
    assert response.status_code==status
    assert response.json['error']==code

def test_stream_and_memory(client):
    def tokens(*args, **kwargs):
        yield 'Compound interest builds over time.'
    with patch.object(chatbot,'get_db',return_value=Mock()), patch.object(chatbot,'_fetch_full_metrics',return_value={}), patch.object(chatbot,'gemini_stream_chat',side_effect=tokens):
        response=client.post('/chat',json={'message':'Explain compound interest'})
        assert response.status_code==200
        assert b'event:done' in response.data
    assert chatbot.conversation_memory[98765][-1]['role']=='assistant'
