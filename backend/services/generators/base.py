"""Abstract generator interface — swap OpenSCAD for CadQuery (or other) later."""
from abc import ABC, abstractmethod
from services.ir.schema import IRTree


class CADGenerator(ABC):

    @abstractmethod
    def generate_code(self, ir: IRTree) -> str:
        """Return source-code text (e.g. .scad, .py) for the given IR tree."""

    @abstractmethod
    def file_extension(self) -> str:
        """Source-file extension, without the leading dot (e.g. 'scad')."""
