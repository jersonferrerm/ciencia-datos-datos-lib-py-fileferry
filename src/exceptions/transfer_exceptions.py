"""
Jerarquía de excepciones personalizadas para la librería S3-SFTP Transfer.

Este módulo define todas las excepciones específicas de la librería,
proporcionando una jerarquía clara para el manejo de errores.
"""


class TransferLibraryError(Exception):
    """
    Excepción base para todas las excepciones de la librería S3-SFTP Transfer.

    Todas las excepciones específicas de la librería deben heredar de esta clase
    para permitir un manejo de errores consistente.
    """

    def __init__(self, message: str, error_code: str = None, context: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class ConfigurationError(TransferLibraryError):
    """
    Error de configuración de la librería.

    Se lanza cuando hay problemas con la configuración de variables de entorno,
    parámetros inválidos o configuración faltante.
    """


class ValidationError(TransferLibraryError):
    """
    Error de validación de datos o parámetros.

    Se lanza cuando los datos de entrada no cumplen con los criterios
    de validación requeridos.
    """


class TransferError(TransferLibraryError):
    """
    Error general de transferencia de archivos.

    Se lanza cuando ocurren errores durante las operaciones de transferencia
    que no se clasifican en otras categorías específicas.
    """


class ThrottleError(TransferLibraryError):
    """
    Error de throttling o límite de velocidad.

    Se lanza cuando se exceden los límites de velocidad o throughput
    permitidos por el servicio.
    """


class ConnectionError(TransferLibraryError):
    """
    Error de conexión con servicios externos.

    Se lanza cuando hay problemas de conectividad con AWS Transfer Family,
    S3 u otros servicios externos.
    """


class AuthenticationError(TransferLibraryError):
    """
    Error de autenticación.

    Se lanza cuando hay problemas con credenciales o permisos de acceso
    a los servicios AWS.
    """


class TimeoutError(TransferLibraryError):
    """
    Error de timeout en operaciones.

    Se lanza cuando las operaciones exceden el tiempo límite establecido.
    """


class FileNotFoundError(TransferLibraryError):
    """
    Error cuando un archivo no se encuentra.

    Se lanza cuando se intenta acceder a un archivo que no existe
    en el origen o destino especificado.
    """


class InsufficientPermissionsError(TransferLibraryError):
    """
    Error de permisos insuficientes.

    Se lanza cuando el usuario o servicio no tiene los permisos necesarios
    para realizar la operación solicitada.
    """
