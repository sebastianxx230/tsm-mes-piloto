from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8-sig')


def test_material_symbols_load_before_tailwind_utilities():
    base_template = read('templates/base.html')

    material_position = base_template.index('Material+Symbols+Rounded')
    tailwind_position = base_template.index("css/tailwind.generated.css")

    assert material_position < tailwind_position


def test_mutating_pages_keep_same_origin_referrer_for_https_csrf():
    tracking_template = read('templates/seguimiento.html')
    report_template = read('templates/reporte_selector.html')

    assert '<meta name="referrer" content="same-origin">' in tracking_template
    assert '<meta name="referrer" content="same-origin">' in report_template
    assert '<meta name="referrer" content="no-referrer">' not in tracking_template
    assert '<meta name="referrer" content="no-referrer">' not in report_template
    assert 'referrerpolicy="no-referrer"' in report_template


def test_hidden_material_icons_cannot_override_visibility():
    base_css = read('static/css/base.css')

    assert '.material-symbols-rounded.hidden' in base_css
    assert 'display: none !important' in base_css


def test_login_uses_one_accessible_password_visibility_icon():
    login_template = read('templates/login.html')
    login_script = read('static/js/login.js')
    login_css = read('static/css/login.css')

    assert login_template.count('id="passwordVisibilityIcon"') == 1
    assert 'id="eyeClosed"' not in login_template
    assert 'id="eyeOpen"' not in login_template
    assert "visibilityIcon.textContent" in login_script
    assert "aria-pressed" in login_script
    assert 'Producción conectada.' in login_template
    assert 'login.css' in login_template and '?v=2.1.0' in login_template
    assert '@media (min-width: 900px) and (max-width: 1023px)' in login_css
    assert 'Información trazable.' in login_template
    assert 'Integra producción, almacén, documentación e indicadores' in login_template
    assert 'Control y <span' not in login_template


def test_catalog_keeps_compact_original_structure():
    catalog_template = read('templates/catalogo_ot.html')

    assert 'class="tsm-page ' in catalog_template
    assert 'Planificación y trazabilidad' not in catalog_template
    assert 'id="catalog-page-title"' not in catalog_template
    catalog_css = read('static/css/catalogo.css')
    assert 'catalog-toolbar' in catalog_template
    assert 'catalog-primary-action' in catalog_template
    assert 'border-l-[3px]' not in catalog_template
    assert '.ot-row-desktop[data-state*="proceso"]' in catalog_css
    assert 'grid-template-columns: minmax(280px, 1fr) auto;' in catalog_css


def test_production_toolbar_chat_and_matrix_share_stable_layout_contracts():
    production_template = read('templates/produccion.html')
    production_css = read('static/css/produccion.css')
    production_script = read('static/js/produccion.js')

    assert 'production-page-header' not in production_template
    assert 'production-v3-toolbar' in production_template
    assert 'production-v3-toolbar-actions' in production_template
    assert 'production-chat-drawer' in production_template
    assert 'production-chat-context' not in production_template
    assert 'Canal operativo' not in production_template
    assert 'Mensajes de la OT' not in production_template
    assert 'precision_manufacturing' not in production_template
    assert 'Inicio de Mensajer' not in production_script
    assert 'coordinación operativa' not in production_script
    assert 'production-chat-message' in production_script
    assert 'production-chat-avatar' in production_script
    assert 'production-chat-avatar' in production_css
    assert 'Mensajes 3.8: comparte el panel sobrio y estable de Seguimiento.' in production_css
    assert 'height: min(570px, calc(100dvh - 104px));' in production_css
    assert 'background: transparent;' in production_css
    assert 'backdrop-filter: none;' in production_css

    assert '--matrix-frozen-width: 572px;' in production_css
    assert '.sticky-c5 {' in production_css
    assert '.sticky-c5 { position: sticky; left: 0;' in production_css
    assert '.sticky-corner-l { position: relative;' in production_css
    assert '#matriz-body .row-total-percentage' in production_css
    assert 'background: #0f172a !important;' in production_css
    assert 'var(--matrix-header-first-row)' in production_css
    assert 'configurarMatrizDesplazable();' in production_script
    assert 'requestAnimationFrame' in production_script
    assert 'ResizeObserver' in production_script
    assert 'id="global-peso-fabricacion"' in production_template
    assert 'Peso U. kg' in production_template
    assert 'Peso T. kg' in production_template
    assert 'function detectarColumnasAbastecimiento(row)' in production_script
    assert "'PERNERIA:TEMPLATE': 'P-TEMP'" in production_script
    assert 'production-group-scope' in production_css
    assert 'class="production-matrix-toolbar"' in production_template
    assert 'id="btn-guardar-avances"' in production_template
    assert '<span>Guardar cambios</span>' in production_template
    assert 'class="production-route-picker"' in production_template
    assert '<select id="import-route-select"' not in production_template
    assert 'function seleccionarRutaImportacion' in production_script
    assert '.production-matrix-toolbar-actions {' in production_css
    assert 'El Excel coincide con la información guardada.' in production_script
    assert 'importedFingerprint === loadedComponentsFingerprint' in production_script


def test_mes_navigation_is_text_only_and_dashboard_refreshes_without_layout_shift():
    navigation = read('templates/_mes_navigation.html')
    dashboard = read('templates/mes_dashboard.html')
    dashboard_script = read('static/js/mes_dashboard.js')

    assert 'material-symbols-rounded' not in navigation
    assert '<span>Almacén</span>' in navigation
    assert 'Kardex' not in navigation
    assert 'mes-nav-refresh' not in navigation
    assert 'id="dashboard-load-status"' not in dashboard
    assert dashboard.count('mes-panel-loading-label') == 4
    assert 'data-refresh-interval="15000"' in dashboard
    assert 'window.setInterval(() =>' in dashboard_script
    assert 'if (loadInFlight) return;' in dashboard_script
    assert "if (!document.hidden) load();" in dashboard_script


def test_messages_and_history_share_the_same_surface_components():
    tracking_template = read('templates/seguimiento.html')
    tracking_css = read('static/css/seguimiento.css')
    tracking_script = read('static/js/seguimiento.js')

    assert tracking_template.count('class="tracking-readonly-note"') == 1
    assert 'class="tracking-readonly-status"' in tracking_template
    assert '>visibility</span>' not in tracking_template
    assert 'precision_manufacturing' not in tracking_template
    assert '<h2 id="tracking-activity-title">Mensajes e historial</h2>' not in tracking_template
    assert '<h2 id="tracking-activity-title">OT {{ ot.ot }}</h2>' in tracking_template
    assert 'aria-label="Mensajes e historial de la OT {{ ot.ot }}"' in tracking_template
    assert '.tracking-message-entry,' in tracking_css
    assert '.tracking-audit-entry,' in tracking_css
    assert 'Actividad compacta y coherente con la mensajeria de Produccion.' in tracking_css
    assert '.tracking-message-entry .tracking-activity-copy > p' in tracking_css
    assert '.tracking-message-entry.is-current-user {' in tracking_css
    assert 'Mensajes 8.3: altura estable y burbujas ajustadas al contenido.' in tracking_css
    assert 'width: fit-content;' in tracking_css
    assert 'height: min(570px, calc(100dvh - 104px));' in tracking_css
    assert 'class="tracking-chat-avatar"' not in tracking_template
    assert 'currentUserId' in tracking_script
    scroll_lock = tracking_script.split('function syncBodyScrollLock()', 1)[1].split('function openActivityDrawer', 1)[0]
    assert 'activityBackdrop' not in scroll_lock
    assert '.tracking-audit-entry {' in tracking_css

    assert 'class="tracking-order-card"' not in tracking_template
    assert 'class="tracking-v3-toolbar"' in tracking_template
    assert '<span>Volver al catálogo</span>' in tracking_template
    assert '<span>Abrir producción</span>' in tracking_template
    assert '>factory</span><span>Abrir producción</span>' not in tracking_template
    assert tracking_template.count('data-open-activity') == 1
    assert 'Seguimiento 8.7: resumen compacto' in tracking_css
    assert 'Seguimiento 8.8: KPI y navegación operativa compactos.' in tracking_css
    assert 'Seguimiento 8.9: evidencia y documentos con controles compactos unificados.' in tracking_css
    assert 'Seguimiento 8.10: cabeceras equivalentes en los cinco módulos de detalle.' in tracking_css
    assert 'Seguimiento 8.11: control derecho realmente compacto y consistente.' in tracking_css
    assert 'Seguimiento 8.12: Actividad conserva el mismo contenedor que Volver al catálogo.' in tracking_css
    assert 'grid-template-columns: minmax(220px, 1.3fr) repeat(4, minmax(92px, 1fr)) !important;' in tracking_css
    assert 'font-size: 10.5px !important;' in tracking_css
    assert 'Elige hasta {{ max_tracking_photos }} imágenes para publicar en seguimiento.' in tracking_template
    assert 'Selecciona o sube el archivo que se mostrará en seguimiento.' in tracking_template


def test_authenticated_header_uses_a_compact_primary_role_label():
    base_template = read('templates/base.html')

    assert "'administrador_sistema': 'Administrador'" in base_template
    assert 'active_header_roles[0] if active_header_roles else none' in base_template
    assert "active_header_roles|length - 1" in base_template
    assert 'max-w-[150px]' in base_template


def test_empty_document_states_are_centered_in_the_panel():
    document_css = read('static/css/seguimiento_documentos.css')

    assert '.tracking-document-list {' in document_css
    assert 'justify-content: center;' in document_css
    assert '.tracking-document-empty {' in document_css
    assert 'width: 100%;' in document_css
    assert 'align-items: center;' in document_css
    assert 'text-align: center;' in document_css


def test_tracking_workspace_has_no_decorative_material_icons():
    tracking_template = read('templates/seguimiento.html')
    tracking_script = read('static/js/seguimiento.js')
    document_script = read('static/js/seguimiento_documentos.js')

    assert '>deployed_code</' not in tracking_template
    assert '>engineering</' not in tracking_template
    assert 'tracking-lot-icon material-symbols-rounded' not in tracking_script
    assert "'tracking-avatar', person.initials" not in tracking_script
    assert 'tracking-document-open-indicator material-symbols-rounded' not in document_script


def test_tracking_workspace_uses_one_layout_and_expandable_lot_details():
    tracking_template = read('templates/seguimiento.html')
    tracking_script = read('static/js/seguimiento.js')
    tracking_css = read('static/css/seguimiento.css')
    document_css = read('static/css/seguimiento_documentos.css')

    assert tracking_template.count('class="tracking-workspace-copy"') == 5
    assert tracking_template.count('class="tracking-workspace-actions"') == 5
    assert 'data-lot-toggle aria-expanded="false"' in tracking_template
    assert 'class="tracking-lot-process-grid"' in tracking_template
    assert 'Gestionar fotografías' in tracking_template
    assert 'Gestionar plano' in tracking_template
    assert 'Gestionar documentos' in tracking_template
    assert 'id="tracking-photo-upload"' in tracking_template
    assert 'id="tracking-document-upload"' in tracking_template
    assert 'uploadPhotoUrl' in tracking_template
    assert 'uploadDocumentUrlTemplate' in tracking_template
    assert 'function uploadTrackingPhotos(input)' in tracking_script
    assert 'function uploadDocument(input)' in read('static/js/seguimiento_documentos.js')
    assert 'const trackingViewHashes' in tracking_script
    assert 'function setupLotDetails()' in tracking_script
    assert 'Workspace 8.0: única fuente visual' in tracking_css
    assert 'Documentos 2.0: comparte la misma cabecera' in document_css


def test_tracking_workspace_styles_load_in_canonical_order_and_preview_decodes_images():
    tracking_template = read('templates/seguimiento.html')
    tracking_script = read('static/js/seguimiento.js')

    document_css_position = tracking_template.index("css/seguimiento_documentos.css")
    workspace_css_position = tracking_template.index("css/seguimiento.css")
    assert document_css_position < workspace_css_position
    assert 'Ver participación' in tracking_template
    assert 'data-photo-preview-loading' in tracking_template
    assert 'function preloadPhoto(url)' in tracking_script
    assert "image.decoding = 'async';" in tracking_script
