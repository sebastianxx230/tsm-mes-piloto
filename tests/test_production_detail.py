import re
from pathlib import Path


def test_production_detail_uses_a_compact_operational_layout(client, login, ids):
    login('admin')

    response = client.get(f"/produccion/{ids['ot']}")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="production-detail-overlay hidden opacity-0"' in page
    assert 'Ficha operativa del elemento' in page
    assert 'Avance registrado' in page
    assert 'por proceso' in page
    assert 'id="det-porcentaje-track"' in page


def test_element_detail_stays_above_the_maximized_matrix():
    css = Path('static/css/produccion.css').read_text(encoding='utf-8-sig')
    javascript = Path('static/js/produccion.js').read_text(encoding='utf-8-sig')

    maximized_match = re.search(
        r'\.table-maximized\s*\{[^}]*z-index:\s*(\d+)',
        css,
        flags=re.DOTALL,
    )
    detail_match = re.search(
        r'\.production-detail-overlay\s*\{[^}]*z-index:\s*(\d+)',
        css,
        flags=re.DOTALL,
    )

    assert maximized_match is not None
    assert detail_match is not None
    assert int(detail_match.group(1)) > int(maximized_match.group(1))
    assert "overlay.setAttribute('aria-hidden', 'false')" in javascript
    assert "currentDetalleRow.querySelector('.btn-detalle')" in javascript
