"""Minimal in-process CQRS bus with typed handlers.

Commands mutate state and return a result; queries are read-only. Handlers are
registered at application start-up, which keeps transport (HTTP, gRPC, Celery)
decoupled from use-cases.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from app.core.exceptions import BadRequestError
from app.core.logging import get_logger

log = get_logger("ofme.cqrs")

C = TypeVar("C")
R = TypeVar("R")


@dataclass(slots=True)
class Command(Generic[R]):
    """Base class for write operations."""


@dataclass(slots=True)
class Query(Generic[R]):
    """Base class for read operations."""


Handler = Callable[[Any], Awaitable[Any]]


@dataclass(slots=True)
class HandlerRegistry:
    _handlers: dict[type, Handler] = field(default_factory=dict)

    def register(self, message_type: type, handler: Handler) -> None:
        if message_type in self._handlers:
            raise BadRequestError(f"Handler already registered for {message_type.__name__}")
        self._handlers[message_type] = handler
        log.debug("cqrs.handler_registered", message=message_type.__name__)

    def resolve(self, message_type: type) -> Handler:
        handler = self._handlers.get(message_type)
        if handler is None:
            raise BadRequestError(f"No handler registered for {message_type.__name__}")
        return handler

    @property
    def size(self) -> int:
        return len(self._handlers)


class CommandBus:
    def __init__(self) -> None:
        self.registry = HandlerRegistry()

    def register(self, command_type: type, handler: Handler) -> None:
        self.registry.register(command_type, handler)

    async def dispatch(self, command: Any) -> Any:
        handler = self.registry.resolve(type(command))
        log.debug("cqrs.command", command=type(command).__name__)
        result = handler(command)
        if inspect.isawaitable(result):
            return await result
        return result


class QueryBus:
    def __init__(self) -> None:
        self.registry = HandlerRegistry()

    def register(self, query_type: type, handler: Handler) -> None:
        self.registry.register(query_type, handler)

    async def ask(self, query: Any) -> Any:
        handler = self.registry.resolve(type(query))
        log.debug("cqrs.query", query=type(query).__name__)
        result = handler(query)
        if inspect.isawaitable(result):
            return await result
        return result


command_bus = CommandBus()
query_bus = QueryBus()
