"""Cotización de cada familia de productos con un catálogo realista."""
from decimal import Decimal

import pytest

from app.db.models import ProductAcabadoEnum as A, ProductCategoryEnum as C
from app.schemas.quote import QuoteLineInput
from app.services import quote_service
from app.tests.test_quotes import _only_these_products, seed_quote_product

CATALOGO = [
    ('Tubo negro redondo 2" x 6 m', C.tubos, A.negro, '2"', "2 mm"),
    ("Tubo cuadrado 40x40 mm x 6 m", C.tubos, A.negro, "40x40 mm", "2 mm"),
    ('Tubo galvanizado redondo 1 1/2" x 6 m', C.tubos, A.galvanizado, '1 1/2"', "1.5 mm"),
    ('Perfil ángulo 2" x 1/4" x 6 m', C.perfiles, None, '2"', '1/4"'),
    ('Fierro corrugado 5/8" x 9 m', C.fierros, None, '5/8"', None),
    ('Fierro cuadrado liso 1/2" x 6 m', C.fierros, None, '1/2"', None),
    ("Plancha LAF 1.5 mm 1.20 x 2.40 m", C.planchas, None, "1.20 x 2.40 m", "1.5 mm"),
    ("Plancha LAC 2 mm 1.20 x 2.40 m", C.planchas, None, "1.20 x 2.40 m", "2 mm"),
    ("Disco de corte para metal 4 1/2 pulgadas", C.accesorios, None, None, None),
    ("Disco de desbaste para metal 4 1/2 pulgadas", C.accesorios, None, None, None),
    ("Guincha (wincha) metálica 8 m", C.accesorios, None, "8 m", None),
    ("Guincha (wincha) metálica 5 m", C.accesorios, None, "5 m", None),
    ("Careta de soldar", C.accesorios, None, None, None),
]

CASOS = [
    ("3 tubos redondos de 2 pulgadas 2mm negro", 'Tubo negro redondo 2" x 6 m'),
    ("5 tubos cuadrados 40x40 de 2mm negro", "Tubo cuadrado 40x40 mm x 6 m"),
    ("2 tubos galvanizados redondos de 1 1/2 1.5mm", 'Tubo galvanizado redondo 1 1/2" x 6 m'),
    ("3 unidades de angulo de 2 1/2 pulgadas x 1/4", None),  # 2 1/2" no existe: sugiere, no pide espesor
    ("3 angulos de 2 pulgadas x 1/4", 'Perfil ángulo 2" x 1/4" x 6 m'),
    ("3 angulos 2 x 1/4", 'Perfil ángulo 2" x 1/4" x 6 m'),
    ("10 fierros corrugados de 5/8", 'Fierro corrugado 5/8" x 9 m'),
    ("5 cuadro liso de 1/2", 'Fierro cuadrado liso 1/2" x 6 m'),
    ("fierro cuadrado liso 1/2 pulgada", 'Fierro cuadrado liso 1/2" x 6 m'),
    ("2 planchas lac 2mm", "Plancha LAC 2 mm 1.20 x 2.40 m"),
    ("2 planchas laf 1.5 mm", "Plancha LAF 1.5 mm 1.20 x 2.40 m"),
    ("3 discos de desbaste", "Disco de desbaste para metal 4 1/2 pulgadas"),
    ("3 discos de corte", "Disco de corte para metal 4 1/2 pulgadas"),
    ("2 guinchas de 8 m", "Guincha (wincha) metálica 8 m"),
    ("1 wincha de 5 metros", "Guincha (wincha) metálica 5 m"),
    ("1 careta", "Careta de soldar"),
]


@pytest.fixture()
def catalogo(db_session):
    _only_these_products(db_session)
    for nombre, categoria, acabado, medida, espesor in CATALOGO:
        seed_quote_product(
            db_session, nombre=nombre, categoria=categoria, acabado=acabado,
            medida=medida, espesor=espesor, precio_unitario=Decimal("10.00"),
        )


@pytest.mark.parametrize("texto,esperado", CASOS)
def test_cada_categoria_se_cotiza_sin_preguntas_de_mas(db_session, catalogo, texto, esperado):
    item = quote_service.parse_list(texto)[0]
    result = quote_service.match_item(db_session, item)

    assert result["faltantes"] == []
    if esperado is None:
        assert result["status"] == "no_se_vende"
        assert result["options"]
    else:
        assert result["status"] == "con_precio"
        assert result["product"].nombre == esperado


def test_plancha_sin_tipo_pregunta_solo_el_tipo(db_session, catalogo):
    item = quote_service.parse_list("2 planchas de 2 mm")[0]
    result = quote_service.match_item(db_session, item)

    assert result["status"] == "faltan_datos"
    assert result["faltantes"] == ["tipo"]


def test_accesorio_con_palabra_desconocida_no_se_asigna_a_otro(db_session, catalogo):
    item = quote_service.parse_list("3 discos de lija")[0]
    result = quote_service.match_item(db_session, item)

    assert result["status"] != "con_precio"


@pytest.mark.parametrize(
    "texto,faltantes,forma,acabado",
    [
        ("5 tubos de 40x40", ["espesor", "acabado"], "cuadrado", None),
        ("5 tubos de 40 x 20", ["espesor", "acabado"], "rectangular", None),
        ("5 tubos de 2 pulgadas", ["forma", "espesor", "acabado"], None, None),
        ("5 tubos redondos de 2 pulgadas 2mm", ["acabado"], "redondo", None),
        ("5 tubos 40x40 2mm lac", [], "cuadrado", "negro"),
        ("5 tubos 40x40 2mm negro", [], "cuadrado", "negro"),
        ("5 tubos 40x40 2mm laf", [], "cuadrado", "laf"),
        ("5 tubos 40x40 2mm galvanizado", [], "cuadrado", "galvanizado"),
    ],
)
def test_tubos_piden_solo_lo_esencial(texto, faltantes, forma, acabado):
    attrs = quote_service.extract_attributes(quote_service.parse_list(texto)[0])

    assert attrs["faltantes"] == faltantes
    assert attrs["forma"] == forma
    assert attrs["acabado"] == acabado


@pytest.mark.parametrize(
    "texto,forma,medida,espesor,faltantes",
    [
        ("tubo de 40 x 1.8 galvanizado", None, "40", "1.8 mm", ["forma"]),
        ("tubo redondo 40 x 1.8 galvanizado", "redondo", "40", "1.8 mm", []),
        ("tubo 40x40x1.8 galvanizado", "cuadrado", "40 x 40", "1.8 mm", []),
        ("tubo 50x25x1.5 negro", "rectangular", "50 x 25", "1.5 mm", []),
    ],
)
def test_tubo_con_espesor_sin_unidad(texto, forma, medida, espesor, faltantes):
    attrs = quote_service.extract_attributes(quote_service.parse_list(texto)[0])

    assert (attrs["forma"], attrs["medida"], attrs["espesor"]) == (forma, medida, espesor)
    assert attrs["faltantes"] == faltantes


@pytest.mark.parametrize(
    "texto,esperado,cantidad",
    [
        ("Necesito cotizar 5 tubos de 2 pulgadas", "5 tubos de 2 pulgadas", 5),
        ("Hola buenas tardes, quisiera 3 planchas lac 2mm por favor gracias", "3 planchas lac 2mm", 3),
        ("Hola, me puedes cotizar 10 fierros corrugados de 5/8?", "10 fierros corrugados de 5/8", 10),
        ("Necesito cotizar el siguiente material: 3 unidades de angulo de 2 x 1/4", "3 unidades de angulo de 2 x 1/4", 3),
    ],
)
def test_saludos_no_quedan_en_la_linea(texto, esperado, cantidad):
    item = quote_service.parse_list(texto)[0]

    assert item.texto_original == esperado
    assert item.cantidad == Decimal(cantidad)
    assert item.cantidad_asumida is False


def test_solo_un_saludo_no_genera_lineas():
    with pytest.raises(ValueError):
        quote_service.parse_list("hola buenas tardes")
