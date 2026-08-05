from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8-sig')


def test_material_symbols_load_before_tailwind_utilities():
    base_template = read('templates/base.html')

    material_position = base_template.index('Material+Symbols+Rounded')
    tailwind_position = base_template.index("css/tailwind.generated.css")

    assert material_position < tailwind_position


def test_hidden_material_icons_cannot_override_visibility():
    base_css = read('static/css/base.css')

    assert '.material-symbols-rounded.hidden' in base_css
    assert 'display: none !important' in base_css


def test_login_uses_one_accessible_password_visibility_icon():
    login_template = read('templates/login.html')
    login_script = read('static/js/login.js')

    assert login_template.count('id="passwordVisibilityIcon"') == 1
    assert 'id="eyeClosed"' not in login_template
    assert 'id="eyeOpen"' not in login_template
    assert "visibilityIcon.textContent" in login_script
    assert "aria-pressed" in login_script


def test_catalog_keeps_compact_original_structure():
    catalog_template = read('templates/catalogo_ot.html')

    assert 'class="tsm-page ' in catalog_template
    assert 'Planificación y trazabilidad' not in catalog_template
    assert 'id="catalog-page-title"' not in catalog_template


def test_messages_and_history_share_the_same_surface_components():
    tracking_template = read('templates/seguimiento.html')
    tracking_css = read('static/css/seguimiento.css')

    assert tracking_template.count('class="tracking-readonly-note"') == 2
    assert '.tracking-message-entry,' in tracking_css
    assert '.tracking-audit-entry,' in tracking_css
    assert 'Actividad compacta y coherente con la mensajeria de Produccion.' in tracking_css
    assert '.tracking-message-entry .tracking-activity-copy > p' in tracking_css
    assert '.tracking-message-entry.is-current-user {' in tracking_css
    assert 'currentUserId' in read('static/js/seguimiento.js')
    assert '.tracking-audit-entry {' in tracking_css


def test_empty_document_states_are_centered_in_the_panel():
    document_css = read('static/css/seguimiento_documentos.css')

    assert '.tracking-document-list {' in document_css
    assert 'justify-content: center;' in document_css
    assert '.tracking-document-empty {' in document_css
    assert 'width: 100%;' in document_css
    assert 'align-items: center;' in document_css
    assert 'text-align: center;' in document_css
