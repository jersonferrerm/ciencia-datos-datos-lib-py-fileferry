# File Ferry Lambda

## Descripción

File Ferry es un servicio Lambda que facilita la transferencia de archivos entre Amazon S3 y servidores SFTP utilizando AWS Transfer Family. Proporciona una interfaz HTTP unificada para operaciones de carga, descarga, eliminación, listado de directorios y consulta de estado de transferencias.

### Características principales:
- **Upload**: Carga de archivos desde S3 hacia servidores SFTP
- **Download**: Descarga de archivos desde servidores SFTP hacia S3
- **Delete**: Eliminación de archivos en servidores SFTP
- **List Directory**: Listado de contenido de directorios SFTP
- **Get Status**: Consulta del estado de transferencias

## Operaciones y Payloads

La respuesta estándar de la Lambda es la siguiente:
```json
"statusCode": 200,
"headers": {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization"
},
"body": "{}"
```

**Nota importante:** Todos los ejemplos de respuestas que se van mostrar de ahora en adelante, son las estructuras que estarían dentro del string del body de la respuesta estándar, transformadas a un formato JSON.


### 1. Upload (S3 → SFTP)

Carga archivos desde S3 hacia un servidor SFTP.

**Payload:**
```json
{
  "operation": "upload",
  "connector_id": "c-1234567890abcdef0",
  "files": [
    "/mi-bucket/archivo1.txt",
    "/mi-bucket/carpeta/archivo2.pdf"
  ],
  "destination_path": "/sftp/destino/"
}
```
**Nota importante:** Los conectores de Transfer Family solo admiten la ruta completa al archivo de origen en S3, no es posible enviarles rutas de carpetas del estilo ```/mi-bucket/carpeta/``` o con wildcards como ```/mi-bucket/carpeta/*```

**Respuesta exitosa:**
```json
{
  "success": true,
  "data": {
    "status": "COMPLETED",
    "error_message": null,
    "batch_results": [
      {
        "transfer_id": "t-0987654321fedcba0",
        "file_results": [
          {
            "file_path": "/sftp/origen/archivo1.txt",
            "status": "TRANSFERRING",
            "error_message": null
          }
        ]
      }
    ]
  },
  "timestamp": "2025-01-15T10:35:00.000Z"
}
```

### 2. Download (SFTP → S3)

Descarga archivos desde un servidor SFTP hacia S3.

**Payload:**
```json
{
  "operation": "download",
  "connector_id": "c-1234567890abcdef0",
  "files": [
    "/sftp/origen/archivo1.txt",
    "/sftp/origen/archivo2.pdf"
  ],
  "s3_destination_path": "/mi-bucket/descargas/"
}
```

**Respuesta exitosa:**
```json
{
  "success": true,
  "data": {
    "status": "COMPLETED",
    "error_message": null,
    "batch_results": [
      {
        "transfer_id": "t-0987654321fedcba0",
        "file_results": [
          {
            "file_path": "/sftp/origen/archivo1.txt",
            "status": "TRANSFERRING",
            "error_message": null
          }
        ]
      }
    ]
  },
  "timestamp": "2025-01-15T10:35:00.000Z"
}
```
**Nota importante:** Los conectores de Transfer Family solo admiten la ruta completa al archivo de origen en el servidor SFTP, no es posible enviarles rutas de carpetas del estilo ```/sftp/origen/``` o con wildcards como ```/sftp/origen/*```

### 3. Delete

Elimina archivos en un servidor SFTP.

**Payload:**
```json
{
  "operation": "delete",
  "connector_id": "c-1234567890abcdef0",
  "files": [
    "/sftp/archivo-a-eliminar.txt",
    "/sftp/carpeta/otro-archivo.pdf"
  ]
}
```

**Respuesta exitosa:**
```json
{
  "success": true,
  "data": {
    "status": "COMPLETED",
    "error_message": null,
    "batch_results": [
      {
        "delete_id": "d-1234567890abcdef0",
        "delete_path": "/sftp/archivo-a-eliminar.txt",
        "status": "COMPLETED",
        "error_message": null
      }
    ]
  },
  "timestamp": "2025-01-15T10:40:00.000Z"
}
```
**Nota importante:** La funcionalidad de eliminar, admite rutas de carpetas completas del estilo ```/sftp/carpeta```, pero solo eliminará carpetas ***vacías***. En caso de que la carpeta tenga elementos dentro, no hará ninguna acción. Esto es un comportamiento inherente a los conectores de Transfer Family.

### 4. List Directory

Lista el contenido de un directorio SFTP.

**Payload:**
```json
{
  "operation": "list_directory",
  "connector_id": "c-1234567890abcdef0",
  "sftp_path": "/sftp/directorio",
  "max_items": 100,
  "output_directory_path": "/mi-bucket/listados"
}
```

**Respuesta exitosa:**
```json
{
  "success": true,
  "data": {
    "listing_id": "l-1234567890abcdef0",
    "output_filename": "c-1234567890abcdef0-l-1234567890abcdef0.json",
    "path": "/sftp/directorio"
  },
  "timestamp": "2025-01-15T10:30:00.000Z"
}
```
**Nota importante:** Esta funcionalidad genera un archivo JSON, con los resultados del listado, en la ruta de S3 que se le envía en ***output_directory_path***. Este archivo tiene una estructura de nombre así ```<connector-id>-<listing-id>.json```.

**Archivo con el resultado de listado**
```json
{
  "files": [
    {
      "filePath": "/sftp/directorio/image.jpeg",
      "modifiedTimestamp": "2025-08-05T19:27:30Z",
      "size": 740470
    }
  ],
  "paths": [
    {
      "path": "/sftp/directorio/directorio2"
    }
  ],
  "truncated": false
}
```
**Nota:**
1. El valor de ```truncated``` indica si los resultados están truncados dependiendo de lo que se haya indicado en el ```max_items``` del payload.
2. El valor de ```size``` indica el tamaño del archivo en Bytes.

### 5. Get Status

Consulta el estado de una o múltiples transferencias.

**Payload (transferencia individual):**
```json
{
  "operation": "get_status",
  "transfer_id": "t-1234567890abcdef0"
}
```

**Payload (múltiples transferencias):**
```json
{
  "operation": "get_status",
  "connector_id": "c-1234567890abcdef0",
  "transfer_ids": [
    "t-1234567890abcdef0",
    "t-0987654321fedcba0"
  ]
}
```

**Respuesta exitosa:**
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "transfer_id": "t-0987654321fedcba0",
        "connector_id": "c-1234567890abcdef0",
        "overall_status": "COMPLETED",
        "file_results": [
          {
            "file_path": "/sftp/directorio/archivo.txt",
            "status": "COMPLETED",
            "failure_code": null,
            "failure_message": null
          }
        ],
        "next_token": null,
        "total_files": 10,
        "completed_files": 9,
        "failed_files": 1,
        "in_progress_files": 0,
        "queued_files": 0,
        "timestamp": "2025-09-09T09:28:45.560394"
      }
    ]
  },
  "timestamp": "2025-01-15T10:45:00.000Z"
}
```

## Respuestas de Error

Todas las operaciones pueden devolver errores con el siguiente formato:

```json
{
  "success": false,
  "error": {
    "code": "MISSING_OPERATION",
    "message": "Operation is required (upload, download, delete, list_directory, get_status)"
  },
  "timestamp": "2025-01-15T10:30:00.000Z"
}
```

### Códigos de error comunes:
- `MISSING_OPERATION`: Operación no especificada
- `INVALID_OPERATION`: Operación no válida
- `MISSING_CONNECTOR_ID`: ID de conector requerido
- `EMPTY_FILE_LIST`: Lista de archivos vacía
- `MISSING_DESTINATION_PATH`: Ruta de destino requerida
- `VALIDATION_ERROR`: Error de validación de parámetros
- `CONFIGURATION_ERROR`: Error de configuración
- `TRANSFER_ERROR`: Error durante la transferencia

## Estructura del Proyecto

```console
.
├── README.md
├── requirements.txt
├── src
│   ├── __init__.py
│   ├── clients
│   │   ├── __init__.py
│   │   └── aws_transfer_client.py
│   ├── config
│   │   ├── __init__.py
│   │   └── config_manager.py
│   ├── exceptions
│   │   ├── __init__.py
│   │   └── transfer_exceptions.py
│   ├── index.py
│   ├── models
│   │   ├── __init__.py
│   │   ├── config_models.py
│   │   └── transfer_models.py
│   ├── orchestration
│   │   ├── __init__.py
│   │   ├── batch_orchestrator.py
│   │   ├── session_manager.py
│   │   └── throttle_controller.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── delete_service.py
│   │   ├── download_service.py
│   │   ├── interfaces.py
│   │   ├── listing_service.py
│   │   ├── monitoring_service.py
│   │   └── upload_service.py
│   ├── transfer_manager.py
│   └── utils
│       ├── __init__.py
│       ├── error_handler.py
│       ├── instance_manager.py
│       ├── logger.py
│       └── retry_handler.py
└── test
    ├── __init__.py
    ├── conftest.py
    ├── fixtures
    │   └── __init__.py
    ├── integration
    │   ├── __init__.py
    │   ├── test_aws_integration.py
    │   └── test_delete_integration.py
    ├── test_index.py
    └── unit
        ├── __init__.py
        ├── test_clients
        │   ├── __init__.py
        │   └── test_aws_transfer_client.py
        ├── test_exceptions
        │   ├── __init__.py
        │   └── test_transfer_exceptions.py
        ├── test_index.py
        ├── test_models
        │   ├── __init__.py
        │   ├── test_config_models.py
        │   └── test_transfer_models.py
        ├── test_orchestration
        │   ├── __init__.py
        │   ├── test_batch_orchestrator.py
        │   ├── test_session_manager.py
        │   └── test_throttle_controller.py
        ├── test_services
        │   ├── __init__.py
        │   ├── test_delete_service.py
        │   ├── test_delete_service_batch.py
        │   ├── test_delete_service_extended.py
        │   ├── test_download_service.py
        │   ├── test_listing_service.py
        │   ├── test_monitoring_service.py
        │   └── test_upload_service.py
        ├── test_transfer_manager.py
        ├── test_transfer_manager_additional.py
        └── test_utils
            ├── __init__.py
            ├── test_error_handler.py
            ├── test_instance_manager.py
            └── test_retry_handler.py
```