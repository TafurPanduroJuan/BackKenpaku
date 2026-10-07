import sys
from decimal import Decimal
from pathlib import Path

# Añadir la raíz del proyecto al sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.models import (
    Product,
    ProductAcabadoEnum,
    ProductCategoryEnum,
    User,
    UserRolEnum,
)
from app.db.session import SessionLocal, engine


def seed_database():
    """Carga inicial idempotente de usuario administrador y productos iniciales."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("🌱 Iniciando carga de datos semilla para Comercial Kenpaku S.A.C...")

        # 1. Crear Usuario Administrador si no existe
        admin_email = settings.ADMIN_EMAIL
        existing_admin = (
            db.query(User).filter(User.email == admin_email).first()
        )
        if not existing_admin:
            admin_user = User(
                email=admin_email,
                password_hash=get_password_hash(settings.ADMIN_PASSWORD),
                rol=UserRolEnum.admin,
                activo=True,
            )
            db.add(admin_user)
            print(f"✅ Administrador creado: {admin_email}")
        else:
            existing_admin.password_hash = get_password_hash(settings.ADMIN_PASSWORD)
            existing_admin.rol = UserRolEnum.admin
            existing_admin.activo = True
            print(f"🔄 Administrador {admin_email} sincronizado con ADMIN_PASSWORD.")

        # 2. Productos Iniciales de Acero
        products_data = [
            {
                "nombre": 'Tubo negro redondo 2" x 6 m',
                "categoria": ProductCategoryEnum.tubos,
                "acabado": ProductAcabadoEnum.negro,
                "medida": '2" x 6 m',
                "espesor": "2 mm",
                "descripcion_corta": "Tubo de acero negro estructural redondo de 2 pulgadas y 6 metros de largo.",
                "ficha_tecnica": (
                    'El Tubo negro redondo 2" x 6 m es un elemento de acero estructural de alta resistencia fabricado bajo '
                    'norma ASTM A500 TODO: [validar norma por el propietario]. Su acabado negro conserva la capa de calamina de '
                    "fabricación, ideal para estructuras soldadas en interiores o proyectos de carpintería metálica que recibirán "
                    "pintura anticorrosiva posterior. Medidas estándar: diámetro exterior de 50.8 mm y espesor constante de 2.0 mm. "
                    "Usos recomendados: fabricación de portones, tijerales ligeros, postes de cerco, estructuras publicitarias y "
                    "mobiliario industrial. Diferencia negro vs galvanizado: al no tener recubrimiento de zinc, requiere pintura base "
                    "anticorrosiva para evitar oxidación prematura en ambientes húmedos de Lima costera (Puente Piedra). Advertencias: "
                    "almacenar en lugar seco y bajo techo; evitar el contacto directo con la humedad del suelo durante el almacenamiento. "
                    "TODO: [validar peso exacto por metro por el propietario]."
                ),
                "precio_unitario": Decimal("128.90"),
                "stock_disponible": 15,
                "imagen_url": "https://images.unsplash.com/photo-1535813547-99c456a41d4a?w=600",
                "activo": True,
            },
            {
                "nombre": "Tubo cuadrado 40x40 mm x 6 m",
                "categoria": ProductCategoryEnum.tubos,
                "acabado": ProductAcabadoEnum.ninguno,
                "medida": "40x40 mm x 6 m",
                "espesor": "1.5 mm",
                "descripcion_corta": "Tubo cuadrado de acero comercial para cerrajería y estructuras livianas.",
                "ficha_tecnica": (
                    "Perfil hueco cuadrado de acero de 40x40 mm con espesor de 1.5 mm y longitud de 6 metros. Fabricado mediante "
                    "conformado en frío y soldadura por resistencia eléctrica ERW TODO: [validar proceso por el propietario]. Su sección "
                    "cuadrada uniforme ofrece excelente rigidez a la torsión y facilidad de ensamblaje en cortes a 45 y 90 grados. "
                    "Usos recomendados: marcos de puertas, ventanas, barandas, estructuras para techos livianos, rejas y bastidores. "
                    "Medidas estándar: 40x40 mm exterior, espesor 1.5 mm. Diferencia negro/sin acabado vs galvanizado: expuesto a la intemperie "
                    "sin protección anticorrosiva sufrirá corrosión acelerada por la garúa y salinidad de Lima. Advertencias: aplicar "
                    "imprimante epóxico antes de la pintura final; revisar tolerancias en dimensiones de corte. TODO: [validar limite de "
                    "fluencia por el propietario]."
                ),
                "precio_unitario": Decimal("94.50"),
                "stock_disponible": 12,
                "imagen_url": "https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?w=600",
                "activo": True,
            },
            {
                "nombre": 'Perfil ángulo 2" x 1/4" x 6 m',
                "categoria": ProductCategoryEnum.perfiles,
                "acabado": ProductAcabadoEnum.negro,
                "medida": '2" x 1/4" x 6 m',
                "espesor": '1/4"',
                "descripcion_corta": "Perfil en L de acero laminado en caliente para estructuras pesadas y tijerales.",
                "ficha_tecnica": (
                    'Perfil de acero estructural en L de lados iguales de 2 pulgadas (50.8 mm) por 1/4 pulgada (6.35 mm) de espesor y '
                    "6 metros de largo. Producido bajo norma ASTM A36 TODO: [validar norma por el propietario]. Ofrece alta tenacidad y "
                    "resistencia mecánica en construcciones pesadas. Usos recomendados: tijerales metálicos, soportes de tanques, "
                    "anclajes de concreto, plataformas industriales, marcos de soporte estructural y refuerzos de carrocerías. Medidas "
                    "estándar: alas de 50.8 mm, espesor de 6.35 mm. Diferencia con perfiles galvanizados: el perfil negro requiere arenado o "
                    "limpieza mecánica y pintado antes de su instalación exterior en Lima Norte. Advertencias: para cálculos de carga "
                    "estructural o voladizos, consulte siempre a un ingeniero colegiado; manipular con guantes de cuero por cantos vivos. "
                    "TODO: [validar radio de empalme por el propietario]."
                ),
                "precio_unitario": Decimal("176.00"),
                "stock_disponible": 5,
                "imagen_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600",
                "activo": True,
            },
            {
                "nombre": 'Fierro corrugado 5/8" x 9 m',
                "categoria": ProductCategoryEnum.fierros,
                "acabado": ProductAcabadoEnum.ninguno,
                "medida": '5/8" x 9 m',
                "espesor": '5/8"',
                "descripcion_corta": "Fierro corrugado Grado 60 para refuerzo de concreto armado en edificación.",
                "ficha_tecnica": (
                    "Barra de acero corrugado de 5/8 de pulgada (15.87 mm de diámetro nominal) por 9 metros de longitud. Fabricado bajo "
                    "norma técnica peruana NTP 341.031 Grado 60 TODO: [validar norma por el propietario]. Presenta resaltes (corrugas) de alta "
                    "adherencia para su trabajo conjunto con el concreto armado en edificación civil. Usos recomendados: vigas principales, "
                    "columnas estructurales, zapatas, losas macizas y muros de contención. Medidas estándar: diámetro 15.87 mm, área de "
                    "sección 198 mm². Diferencia con fierros lisos: sus corrugas evitan el deslizamiento interno bajo esfuerzos de tracción. "
                    "Advertencias: no soldar ni doblar en frío más allá de los radios mínimos especificados en el Reglamento Nacional de "
                    "Edificaciones (RNE); almacenar sobre parihuelas para evitar contaminación con grasa o tierra. TODO: [validar esfuerzo "
                    "de fluencia mínimo 4200 kg/cm² por el propietario]."
                ),
                "precio_unitario": Decimal("68.50"),
                "stock_disponible": 25,
                "imagen_url": "https://images.unsplash.com/photo-1541888946425-d0fbb186a5b3?w=600",
                "activo": True,
            },
            {
                "nombre": "Plancha LAF 1.5 mm 1.20 x 2.40 m",
                "categoria": ProductCategoryEnum.planchas,
                "acabado": ProductAcabadoEnum.negro,
                "medida": "1.20 x 2.40 m",
                "espesor": "1.5 mm",
                "descripcion_corta": "Plancha de acero laminado en frío de superficie lisa y alta maleabilidad.",
                "ficha_tecnica": (
                    "Plancha de acero laminado en frío (LAF - Low Alloy Cold Rolled) de 1.5 mm de espesor y formato comercial de 1.20 x 2.40 "
                    "metros. Su proceso de laminación a temperatura ambiente le otorga un acabado superficial liso, limpio, uniforme y de "
                    "tolerancia dimensional precisa. Usos recomendados: fabricación de tableros eléctricos, gabinetes metálicos, puertas "
                    "enrollables, paneles de carrocería, electrodomésticos y ductos. Medidas estándar: 1200 x 2400 mm, espesor 1.5 mm. "
                    "Diferencia LAF vs LAC: la plancha LAF posee mejor acabado estético y facilidad para el plegado de precisión, mientras "
                    "que la LAC es más rugosa y para uso estructural. Advertencias: la lámina LAF es altamente susceptible al óxido "
                    "ambiente si no se engrasa o pinta inmediatamente. TODO: [validar composición química de carbono por el propietario]."
                ),
                "precio_unitario": Decimal("195.00"),
                "stock_disponible": 8,
                "imagen_url": "https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?w=600",
                "activo": True,
            },
            {
                "nombre": "Plancha LAC 2 mm 1.20 x 2.40 m",
                "categoria": ProductCategoryEnum.planchas,
                "acabado": ProductAcabadoEnum.negro,
                "medida": "1.20 x 2.40 m",
                "espesor": "2 mm",
                "descripcion_corta": "Plancha de acero laminado en caliente para uso estructural y naval.",
                "ficha_tecnica": (
                    "Plancha de acero laminado en caliente (LAC) de 2.0 mm de espesor y formato de 1.20 x 2.40 metros. Producida a altas "
                    "temperaturas bajo norma ASTM A1011 / A36 TODO: [validar norma por el propietario]. Posee una textura superficial "
                    "ligeramente rugosa con capa de óxido de molino. Usos recomendados: plataformas de trabajo, bases de maquinaria, "
                    "tolvas, recipientes no presionados, pisos de camiones y estructuras metálicas soldadas. Medidas estándar: 1.20 x 2.40 m, "
                    "espesor 2.0 mm. Diferencia LAC vs LAF: mayor ductilidad y facilidad de soldadura pesada, ideal para corte por plasma "
                    "o oxicorte. Advertencias: remover la calamina mediante decapado o granallado si se requiere pintura de alta adherencia; "
                    "usar protección ocular durante el corte. TODO: [validar tolerancia de espesor por el propietario]."
                ),
                "precio_unitario": Decimal("215.00"),
                "stock_disponible": 18,
                "imagen_url": "https://images.unsplash.com/photo-1535813547-99c456a41d4a?w=600",
                "activo": True,
            },
            {
                "nombre": 'Tubo galvanizado redondo 1 1/2" x 6 m',
                "categoria": ProductCategoryEnum.tubos,
                "acabado": ProductAcabadoEnum.galvanizado,
                "medida": '1 1/2" x 6 m',
                "espesor": "2 mm",
                "descripcion_corta": "Tubo de acero con recubrimiento anticorrosivo de zinc para intemperie.",
                "ficha_tecnica": (
                    'Tubo de acero redondo de 1 1/2 pulgada (48.3 mm) exterior con recubrimiento de zinc por inmersión en caliente '
                    "galvanizado y 6 metros de longitud. Espesor nominal de 2.0 mm TODO: [validar espesor por el propietario]. Ofrece "
                    "máxima protección anticorrosiva catódica. Usos recomendados: redes de agua, pasamanos exteriores, invernaderos, "
                    "estructuras marinas y postes de alumbrado en ambientes de alta humedad como Puente Piedra. Medidas estándar: "
                    "diámetro 48.3 mm, espesor 2.0 mm. Diferencia galvanizado vs negro: resiste hasta 5 veces más a la intemperie sin necesidad "
                    "de pintura adicional. Advertencias: al soldar tubo galvanizado se liberan vapores de óxido de zinc tóxicos; trabajar "
                    "siempre en áreas ventiladas con respirador para humos metálicos. TODO: [validar micras de zinc por el propietario]."
                ),
                "precio_unitario": Decimal("152.00"),
                "stock_disponible": 14,
                "imagen_url": "https://images.unsplash.com/photo-1504917599217-d4dc5ebe6122?w=600",
                "activo": True,
            },
            {
                "nombre": "Plancha galvanizada 1.2 mm 1.20 x 2.40 m",
                "categoria": ProductCategoryEnum.planchas,
                "acabado": ProductAcabadoEnum.galvanizado,
                "medida": "1.20 x 2.40 m",
                "espesor": "1.2 mm",
                "descripcion_corta": "Plancha galvanizada resistente a la intemperie para ductos y canaletas.",
                "ficha_tecnica": (
                    "Plancha de acero recubierta con capa de zinc continuo por ambos lados, con espesor de 1.2 mm y medidas de 1.20 x 2.40 "
                    "metros. Fabricada bajo norma ASTM A653 TODO: [validar norma por el propietario]. Alta resistencia a la corrosión y "
                    "excelente aptitud para conformado. Usos recomendados: canaletas de lluvias, cubiertas para techos, tolvas de descarga, "
                    "conductos de aire acondicionado y tanques de almacenamiento. Medidas estándar: 1.20 x 2.40 m, espesor 1.2 mm. "
                    "Diferencia galvanizada vs LAF/LAC: no requiere pintura protectora inmediata para su exposición al aire libre. "
                    "Advertencias: evitar el contacto directo con ácidos o alcalinos fuertes que degraden el recubrimiento de zinc; usar "
                    "herramientas adecuadas para no rayar la capa protectora. TODO: [validar gramaje de capa G60/G90 por el propietario]."
                ),
                "precio_unitario": Decimal("185.00"),
                "stock_disponible": 0,
                "imagen_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600",
                "activo": True,
            },
        ]

        created_count = 0
        for pdata in products_data:
            existing_p = (
                db.query(Product).filter(Product.nombre == pdata["nombre"]).first()
            )
            if not existing_p:
                prod = Product(**pdata)
                db.add(prod)
                created_count += 1

        db.commit()
        print(f"✅ Se agregaron {created_count} productos nuevos a la base de datos.")
        
   
        if settings.GEMINI_API_KEY:
            from app.services.embeddings import (
                generate_product_embedding_text,
                get_embedding,
            )

            pendientes = (
                db.query(Product)
                .filter(Product.activo == True, Product.embedding == None)  # noqa: E712,E711
                .all()
            )
            for prod in pendientes:
                texto = generate_product_embedding_text(
                    nombre=prod.nombre,
                    categoria=prod.categoria.value,
                    acabado=prod.acabado.value if prod.acabado else "",
                    medida=prod.medida or "",
                    espesor=prod.espesor or "",
                    ficha_tecnica=prod.ficha_tecnica or "",
                )
                prod.embedding = get_embedding(texto)
            db.commit()
            print(f"🧠 Embeddings generados para {len(pendientes)} productos.")
        else:
            print("ℹ️ Sin GEMINI_API_KEY: ejecuta POST /api/admin/knowledge/reindex luego.")
        print("🎉 Semillado completado con éxito.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error durante el semillado: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
