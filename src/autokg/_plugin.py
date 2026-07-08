from __future__ import annotations

from typing import Any, Callable, Optional

import polars as pl

_PLUGIN_REGISTRY: dict[str, dict] = {
    "connectors": {},
    "template_generators": {},
    "serializers": {},
    "preprocessors": {},
    "postprocessors": {},
}


def register_connector(name: str, reader: Callable[..., pl.DataFrame]):
    _PLUGIN_REGISTRY["connectors"][name] = reader


def register_template_generator(name: str, generator: Callable):
    _PLUGIN_REGISTRY["template_generators"][name] = generator


def register_serializer(name: str, serializer: Callable):
    _PLUGIN_REGISTRY["serializers"][name] = serializer


def register_preprocessor(name: str, processor: Callable[[pl.DataFrame], pl.DataFrame]):
    _PLUGIN_REGISTRY["preprocessors"][name] = processor


def register_postprocessor(name: str, processor: Callable[[list[dict]], list[dict]]):
    _PLUGIN_REGISTRY["postprocessors"][name] = processor


def get_connector(name: str) -> Optional[Callable]:
    return _PLUGIN_REGISTRY["connectors"].get(name)


def get_template_generator(name: str) -> Optional[Callable]:
    return _PLUGIN_REGISTRY["template_generators"].get(name)


def get_serializer(name: str) -> Optional[Callable]:
    return _PLUGIN_REGISTRY["serializers"].get(name)


def get_preprocessor(name: str) -> Optional[Callable]:
    return _PLUGIN_REGISTRY["preprocessors"].get(name)


def get_postprocessor(name: str) -> Optional[Callable]:
    return _PLUGIN_REGISTRY["postprocessors"].get(name)


def list_plugins(category: str = "connectors") -> list[str]:
    return list(_PLUGIN_REGISTRY.get(category, {}).keys())


def list_all_plugins() -> dict[str, list[str]]:
    return {cat: list(plugins.keys()) for cat, plugins in _PLUGIN_REGISTRY.items()}


def import_plugin_module(module_path: str):
    import importlib
    importlib.import_module(module_path)


def register_from_module(module):
    if hasattr(module, "CONNECTOR_NAME") and hasattr(module, "read"):
        register_connector(module.CONNECTOR_NAME, module.read)
    if hasattr(module, "TEMPLATE_GENERATOR_NAME") and hasattr(module, "generate"):
        register_template_generator(module.TEMPLATE_GENERATOR_NAME, module.generate)
    if hasattr(module, "SERIALIZER_NAME") and hasattr(module, "serialize"):
        register_serializer(module.SERIALIZER_NAME, module.serialize)
