from .api import ApiInterface, ToolLayer
from .base import FINISH_TOOL

INTERFACES = ("screenshot", "a11y", "api")


def make_interface(name: str, base_url: str, browser=None, layer=None):
    if name == "api":
        return ApiInterface(layer or ToolLayer(base_url))
    from .browser import A11yInterface, ScreenshotInterface
    if browser is None:
        raise ValueError(f"interface {name} needs a browser")
    return (A11yInterface if name == "a11y" else ScreenshotInterface)(browser, base_url)


__all__ = ["FINISH_TOOL", "INTERFACES", "ApiInterface", "ToolLayer", "make_interface"]
