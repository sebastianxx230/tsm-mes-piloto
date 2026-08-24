import json

from controllers import reporte_fotografico_controller as report_controller


REQUIRED_CREDENTIALS = {
    'type': 'service_account',
    'project_id': 'pilot-project',
    'client_email': 'pilot@example.iam.gserviceaccount.com',
    'private_key': '-----BEGIN PRIVATE KEY-----\\ntest\\n-----END PRIVATE KEY-----\\n',
    'token_uri': 'https://oauth2.googleapis.com/token',
}


def _clear_drive_environment(monkeypatch):
    for key in (
        'GOOGLE_CREDENTIALS',
        'GOOGLE_CREDENTIALS_BASE64',
        'GOOGLE_APPLICATION_CREDENTIALS',
        'GOOGLE_SERVICE_ACCOUNT_PROJECT_ID',
        'GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID',
        'GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY',
        'GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL',
        'GOOGLE_SERVICE_ACCOUNT_CLIENT_ID',
        'GOOGLE_SERVICE_ACCOUNT_TOKEN_URI',
    ):
        monkeypatch.delenv(key, raising=False)


def test_drive_credentials_fall_back_from_partial_json_to_file(
    app,
    monkeypatch,
    tmp_path,
):
    _clear_drive_environment(monkeypatch)
    credentials_path = tmp_path / 'service-account.json'
    credentials_path.write_text(
        json.dumps(REQUIRED_CREDENTIALS),
        encoding='utf-8',
    )
    monkeypatch.setenv(
        'GOOGLE_CREDENTIALS',
        json.dumps({'type': 'service_account', 'project_id': 'partial'}),
    )
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(credentials_path))

    with app.app_context():
        loaded = report_controller._load_drive_credential_data()

    assert loaded['client_email'] == REQUIRED_CREDENTIALS['client_email']
    assert '\\n' not in loaded['private_key']


def test_drive_credentials_accept_split_environment(app, monkeypatch):
    _clear_drive_environment(monkeypatch)
    monkeypatch.setenv('GOOGLE_SERVICE_ACCOUNT_PROJECT_ID', 'pilot-project')
    monkeypatch.setenv(
        'GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL',
        REQUIRED_CREDENTIALS['client_email'],
    )
    monkeypatch.setenv(
        'GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY',
        REQUIRED_CREDENTIALS['private_key'],
    )
    monkeypatch.setenv(
        'GOOGLE_SERVICE_ACCOUNT_TOKEN_URI',
        REQUIRED_CREDENTIALS['token_uri'],
    )

    with app.app_context():
        loaded = report_controller._load_drive_credential_data()

    assert loaded['type'] == 'service_account'
    assert loaded['client_email'] == REQUIRED_CREDENTIALS['client_email']
    assert '\\n' not in loaded['private_key']
