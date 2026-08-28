# Producción V2.0 y Packing List V2.1

Esta etapa introduce una base normalizada sin retirar todavía las columnas y
pantallas de la versión piloto. El objetivo es migrar Producción por fases y
mantener operativo el despliegue actual.

## V2.0 Base

- `procesos_produccion`: catálogo extensible de operaciones.
- `rutas_produccion` y `ruta_procesos`: secuencias reutilizables para
  fabricación galvanizada o pintada.
- `avance_elemento_proceso`: aplicabilidad, cantidad y fechas por proceso.
- `roles_sistema`, `permisos_sistema`, `usuario_roles` y `rol_permisos`:
  autorización preparada para usuarios con más de un rol.
- Compatibilidad temporal con `admin`, `editor`, `viewer` y con los campos
  `hab_real`, `arm_real`, `sol_real`, etc.

Los usuarios existentes reciben automáticamente roles V2 equivalentes:

| Rol piloto | Roles V2 iniciales |
| --- | --- |
| `admin` | Administrador del sistema + Producción Oficina |
| `editor` | Producción Oficina |
| `viewer` | Producción Planta |

## V2.1 Importador

Cada elemento puede almacenar:

- categoría y subcategoría;
- unidad, ubicación, perfil y material;
- longitud en milímetros;
- área unitaria y total;
- peso unitario y total;
- fila original del Excel;
- ruta de fabricación e importación de origen.

El Packing List guarda además su `site` o lote. Las importaciones quedan
registradas en `importaciones_packing_list`, incluyendo archivo, hoja, OT
detectada y advertencias.

### Clasificación inicial

- `FABRICACION`: participa de la ruta productiva.
- `PERNERIA`: incluye Template y Torre.
- `SUMINISTRO`: incluye cable de vida, sistema de vientos y otros suministros.
- `OTRO`: reserva para secciones no clasificadas.

Pernería y suministros no reciben una ruta de fabricación ni se mezclan con el
avance productivo de las piezas fabricadas.

En la pantalla operativa se presentan como **Abastecimiento**. Conservan su
cantidad, unidad, descripción, sección de origen y estado logístico, mientras
que las piezas de `FABRICACION` muestran además su peso unitario, peso total y
avance por proceso. El KPI **Peso planificado** suma exclusivamente
`peso_total_kg` de fabricación; pernería y suministros no alteran el porcentaje
físico de taller.

### Validaciones

- Si la OT detectada en el nombre o contenido del Excel no coincide con la OT
  abierta, la importación se bloquea.
- Los elementos de fabricación requieren una ruta seleccionada.
- Cantidades no enteras, negativas o fuera del rango se rechazan.
- Totales de área y peso se calculan desde el valor unitario cuando el Excel no
  los proporciona.
- La operación conserva control de versión para evitar reemplazar cambios de
  otro usuario.

## Despliegue

Las migraciones canónicas son:

1. `20260821_0012_production_v2_base`
2. `20260821_0013_identity_v2_base`

El reparador aditivo de Vercel crea los objetos faltantes mientras el piloto no
tenga una fase de migración previa al despliegue. En una infraestructura con
Docker se debe ejecutar Alembic antes de iniciar la aplicación y desactivar
gradualmente esa reparación en tiempo de ejecución.

## Núcleo operativo actual

- Producción calcula el avance físico de fabricación ponderado por
  `peso_total_kg`; pernería y suministros no alteran ese porcentaje.
- El Dashboard consolida OTs, kilogramos avanzados, procesos, abastecimiento y
  alertas desde la misma fuente de datos normalizada.
- Almacén / Kardex inicia con los requerimientos importados y su estado
  operativo. Todavía no inventa existencias: el saldo auditable se incorporará
  mediante movimientos de entrada, reserva, salida, devolución y ajuste.
- Planeamiento, Calidad, Logística, Comercial y Reportes aparecen como módulos
  próximos para mantener visible la arquitectura sin publicar funciones
  incompletas.

## Siguiente etapa

V2.2 debe cerrar las reglas de precedencia entre procesos, automatizar fechas
por operación y convertir el control inicial de abastecimiento en un Kardex de
movimientos. Los reportes se construirán después sobre estos datos estables.

## Estructura prevista del reporte operativo

El reporte de Producción se implementará después de estabilizar V2.2. No debe
reutilizar la hoja económica `Hoja1` del Packing List ni depender del diseño de
un Excel específico. Se construirá desde datos normalizados y tendrá estas
secciones:

1. Identidad: OT, cliente, estructura, Packing List, site y archivo importado.
2. Resumen: piezas de fabricación, registros de abastecimiento, peso
   planificado, peso completado y avance físico.
3. Procesos: programado, real, porcentaje y fechas por cada operación de la
   ruta seleccionada.
4. Abastecimiento: pernería y suministros agrupados por subcategoría y estado
   logístico.
5. Trazabilidad: advertencias de importación, responsables, incidencias y
   fechas de actualización.

De esta forma el mismo modelo podrá alimentar una vista web, PDF o exportación
Excel sin duplicar cálculos ni convertir el reporte en otra fuente de verdad.
