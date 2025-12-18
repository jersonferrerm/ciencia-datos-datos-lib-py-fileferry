"""
Service interfaces definition.

Este módulo define las interfaces base para servicios de transferencia
y clientes AWS, siguiendo el principio de inversión de dependencias (DIP).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class ITransferService(ABC): # pragma: no cover
    """
    Interfaz base para servicios de transferencia.

    Define el contrato que deben cumplir todos los servicios de transferencia
    (UploadService, DownloadService) para permitir extensibilidad y testabilidad.
    """




class IAWSClient(ABC): # pragma: no cover
    """
    Interfaz base para clientes AWS.

    Define el contrato para interactuar con servicios AWS, específicamente
    AWS Transfer Family. Permite intercambiar implementaciones y facilita testing.
    """

    @abstractmethod
    def start_file_transfer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una transferencia de archivos usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros de la transferencia incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - SendFilePaths: Lista de rutas de archivos a transferir
                - RetrieveFilePaths: Lista de rutas para descarga (opcional)

        Returns:
            Dict[str, Any]: Respuesta de la API con TransferId y otros metadatos

        Raises:
            ConnectionError: Si hay problemas de conectividad con AWS
            TransferError: Si la API devuelve un error
        """
        pass

    @abstractmethod
    def list_file_transfer_results(
        self,
        connector_id: str,
        transfer_id: str,
        next_token: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Lista los resultados de una transferencia de archivos.

        Args:
            connector_id: ID del conector AWS Transfer Family
            transfer_id: ID de ejecución devuelto por start_file_transfer
            next_token: Token para paginación (opcional)
            max_results: Número máximo de resultados a retornar (opcional)

        Returns:
            Dict[str, Any]: Resultados de la transferencia incluyendo:
                - FileTransferResults: Lista de resultados por archivo
                - NextToken: Token para siguiente página (si aplica)

        Raises:
            ConnectionError: Si hay problemas de conectividad con AWS
            ValidationError: Si los parámetros no son válidos
        """
        pass

    @abstractmethod
    def start_directory_listing(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una operación de listado de directorio usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros del listado incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - RemoteDirectoryPath: Ruta del directorio remoto a listar
                - MaxItems: Número máximo de elementos a retornar (opcional)

        Returns:
            Dict[str, Any]: Respuesta de la API con TransferId y otros metadatos

        Raises:
            ConnectionError: Si hay problemas de conectividad con AWS
            TransferError: Si la API devuelve un error
            ValidationError: Si los parámetros son inválidos
        """
        pass

    @abstractmethod
    def start_remote_delete(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una operación de eliminación de archivos remotos usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros de la eliminación incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - RemoteFilePaths: Lista de rutas de archivos a eliminar

        Returns:
            Dict[str, Any]: Respuesta de la API con TransferId y otros metadatos

        Raises:
            ConnectionError: Si hay problemas de conectividad con AWS
            TransferError: Si la API devuelve un error
            ValidationError: Si los parámetros son inválidos
        """
        pass