from fastapi import status

from orderflow.core.errors import ApplicationError


class CategoryNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="category_not_found",
            message="Category was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class CategorySlugConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="category_slug_conflict",
            message="A category with this slug already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class CategoryCycleError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="category_cycle",
            message="A category cannot be moved below itself or one of its descendants",
            status_code=status.HTTP_409_CONFLICT,
        )


class InactiveParentCategoryError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="inactive_parent_category",
            message="An active category must have an active parent",
            status_code=status.HTTP_409_CONFLICT,
        )


class CategoryNotEmptyError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="category_not_empty",
            message="Archive active child categories and products first",
            status_code=status.HTTP_409_CONFLICT,
        )


class ProductNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="product_not_found",
            message="Product was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ProductSlugConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="product_slug_conflict",
            message="A product with this slug already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class ProductSkuConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="product_sku_conflict",
            message="A product with this SKU already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class InactiveProductCategoryError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="inactive_product_category",
            message="An active product must belong to an active category",
            status_code=status.HTTP_409_CONFLICT,
        )


class CatalogWriteConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="catalog_write_conflict",
            message="Catalog data conflicts with an existing record",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidPriceRangeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_price_range",
            message="Minimum price cannot be greater than maximum price",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
