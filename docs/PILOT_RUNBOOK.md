# Operación del piloto MES (30 a 60 días)

## Arquitectura aprobada

- Aplicación: una sola aplicación Flask; no dividirla en microservicios.
- Base de datos: Neon PostgreSQL. `DATABASE_URL` usa el endpoint `-pooler` y
  `MIGRATIONS_DATABASE_URL` usa el endpoint directo.
- Despliegue productivo: una instancia Docker Render Starter para reportes,
  documentos y respuestas de hasta 50 MB.
- Despliegue temporal Vercel: válido para navegación y operaciones ligeras; sus
  funciones limitan solicitudes y respuestas a 4.5 MB. Configure
  `MAX_CONTENT_MB=4` allí.
- Dominio: no es obligatorio para el piloto. Use la URL HTTPS `onrender.com` y
  agregue posteriormente un dominio neutral controlado por el titular.
- Límite de intentos: use Redis compartido en Vercel o en más de una instancia.
  `memory://` solo es correcto para un único contenedor.

Vercel Hobby es exclusivamente personal/no comercial. Para el piloto de la
empresa se debe usar Vercel Pro o un proveedor de contenedores cuyos términos
permitan uso comercial.

## Preparación única

1. Cree un repositorio privado nuevo e importe únicamente el paquete limpio.
2. Rote antes del primer despliegue:
   - contraseña/rol de Neon usado por la aplicación;
   - `SECRET_KEY` (mínimo 32 bytes aleatorios);
   - clave de la cuenta de servicio de Google Drive.
3. Cree dos ramas/bases aisladas en Neon: `preview` y `pilot-production`.
4. Configure secretos por entorno en el proveedor; nunca cargue `.env` o
   `credentials.json` al repositorio.
5. Active protección de rama en `main`: pull request y CI obligatorios.

## Despliegue seguro

1. Ejecute CI y confirme pruebas, auditoría de dependencias y build Docker.
2. Genere y verifique un backup con `docs/BACKUP_RESTORE.md`.
3. Aplique una sola vez las migraciones con la URL directa:

   ```bash
   flask db upgrade
   ```

4. Despliegue primero contra la rama Neon `pilot-preview`.
5. Ejecute la lista de humo de este documento.
6. Despliegue en producción exactamente el mismo commit verificado.
7. Revise `/health/live`, `/health` y logs durante los primeros 30 minutos.

Las migraciones del piloto son aditivas. Si hay que volver a una versión previa
de la aplicación, deje el esquema actualizado y revierta solo el artefacto. No
ejecute `flask db downgrade` durante un incidente sin validar antes una copia.

## Prueba de humo obligatoria

- `/health/live` responde `200` y confirma que el contenedor está operativo.
- `/health` responde `200` y confirma PostgreSQL disponible.
- Admin, editor y lector pueden iniciar sesión; cada rol ve únicamente sus
  acciones permitidas.
- Crear y editar una OT; una segunda pestaña con versión antigua recibe aviso de
  conflicto y no sobrescribe datos.
- Crear packing list, importar Excel y modificar dos procesos seguidos.
- Activar Arenado/Pintado o cambiar un peso, recargar y confirmar persistencia.
- Comprobar que el avance se pondera por cantidad de piezas.
- Archivar una OT y una packing list; confirmar que desaparecen de operación y
  que sus elementos/bitácora continúan en PostgreSQL.
- Generar un reporte pequeño. En el despliegue de contenedor, probar también el
  reporte real más pesado y una descarga de documento grande.
- Verificar que al ocultar Seguimiento no continúan solicitudes cada 15 s.

## Rutina diaria del piloto

- Inicio de turno: `/health`, acceso de editor y OT activa principal.
- Fin de turno: revisar errores HTTP 5xx, conflictos 409 y fallos de Drive.
- Diario: backup lógico cifrado fuera del proveedor y confirmación del backup de
  Neon.
- Semanal: restaurar un backup en una base temporal y probar login/catálogo/OT.
- Mantener un responsable y un canal de incidente; registrar hora, OT afectada,
  usuario, `request_id` y acción tomada.

## Umbrales para actuar

- Cualquier pérdida o sobrescritura de avance: detener ediciones, conservar logs
  y trabajar sobre una copia de base.
- Dos respuestas 5xx consecutivas en la misma operación: volver al artefacto
  anterior y analizar con `request_id`.
- Neon cerca de sus límites de almacenamiento, cómputo o transferencia: subir de
  plan antes de llegar al 80 %.
- Reporte/respuesta mayor a 4.5 MB: usar el despliegue de contenedor; no intentar
  resolverlo elevando `MAX_CONTENT_MB` en Vercel.

## Transición después del piloto

1. Congelar cambios funcionales durante la ventana.
2. Hacer backup final y prueba de restauración.
3. Crear la nueva base, aplicar migraciones y restaurar.
4. Desplegar el mismo commit en el nuevo hosting y validar con su URL temporal.
5. Si ya existe dominio, bajar el TTL DNS y cambiar únicamente el DNS.
6. Mantener el entorno anterior sin permisos de escritura durante siete días.
7. Cambiar hosting y base en ventanas separadas cuando sea posible.
