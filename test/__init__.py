"""
Suite de Pruebas Unitarias para S3-SFTP Transfer Library.

Este paquete contiene todas las pruebas unitarias para la librería S3-SFTP Transfer,
implementando el requerimiento 5.4 de pruebas comprehensivas.

Módulos:
    unit.test_models: Pruebas para modelos de datos y enums
    unit.test_exceptions: Pruebas para jerarquía de excepciones
    unit.test_orchestration: Pruebas para componentes de orquestación
    unit.test_services: Pruebas para servicios de transferencia
    unit.test_transfer_manager: Pruebas para API principal
    fixtures.mock_clients: Clientes mock para pruebas aisladas

Características:
    - Cobertura completa de todos los componentes
    - Simulación de concurrencia Lambda
    - Mocks de servicios AWS
    - Pruebas de casos edge y errores
    - Validación de configuración externa
"""