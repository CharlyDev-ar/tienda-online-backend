from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.admin.articles.schemas import ArticleCreate
from app.api.v1.admin.articles.schemas import ArticleUpdate
from app.api.v1.admin.articles.schemas import UpdateCategory
from app.api.v1.admin.articles.schemas import UpdateBrand
from app.api.v1.admin.articles.schemas import UpdateStatus

from app.enums.movements import MovementType
from app.enums.movements import TargetType
from app.models.brands import Brand
from app.models.categories import Category

from .repository import ArticleRepository
from app.api.v1.admin.brands.repository import BrandRepository
from app.api.v1.admin.categories.repository import CategoryRepository

from app.api.v1.admin.movements.services import ActivityLogService

from app.core.exceptions import ArticleExist, ArticleNotFound
from app.core.exceptions import CategoryNotFound, BrandNotFound

if TYPE_CHECKING:
    from app.models.articles import Article

class ArticleService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.article_repo = ArticleRepository(db=db)        
        self.brand_repo = BrandRepository(db=db)
        self.category_repo = CategoryRepository(db=db)
        self.activity_log = ActivityLogService(db=db)

    # 🔄 CONTEXT MANAGER PRIVADO PARA TRANSACCIONES
    @asynccontextmanager
    async def _transaction(self):
        try:
            yield
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            raise e

    async def create_article(
        self, 
        article: ArticleCreate, 
        user_id: int
    ) -> Article:
        await self.exist_title(title=article.title)

        async with self._transaction():
            article_db = Article(
                title=article.title,
                slug=article.slug,
                detail=article.detail,
                stock=article.stock,
                cost=article.cost,
                price=article.price,
                brand_id=article.brand_id,
                category_id=article.category_id,
                units_type=article.units_type,
                image=article.image,
            )
            next_article = await self.article_repo.create_article(
                article=article_db
            )

            await self.activity_log.create(
                user_id=user_id,
                target_id=str(next_article.id),
                target_type=TargetType.ARTICLE,
                movement_type=MovementType.CREATED,
                details=(
                    f"Nuevo artículo NRO: {next_article.id} "
                    f"{next_article.title} "
                    f"Costo ${next_article.cost} "
                    f"Price ${next_article.price} "
                    f"Stock {next_article.stock}"
                ),
            )   
            await self.db.refresh(next_article)
            return next_article

    async def update_article(
        self,
        data: ArticleUpdate,
        article_id: int, 
        user_id: int
    ) -> Article:
        article_db = await self.exist_article(article_id=article_id)   

        if data.title is not None and data.title != article_db.title:
            await self.exist_title(title=data.title)    

        async with self._transaction():
            updates = data.model_dump(
                exclude_unset=True, 
                exclude_none=True
            )

            next_article = await self.article_repo.update(
                article=article_db,
                updates=updates
            )

            await self.activity_log.create(
                user_id=user_id,
                target_id=str(next_article.id),
                target_type=TargetType.ARTICLE,
                movement_type=MovementType.UPDATED,
                details=f"Se actualizó el artículo NRO: {next_article.id}",                
            )

            await self.db.refresh(next_article)
            return next_article            

    async def change_status(
        self, 
        data: UpdateStatus, 
        article_id: int, 
        user_id: int
    ) -> Article:
        article_db = await self.exist_article(article_id=article_id)

        async with self._transaction():
            previous_state = article_db.status
            updates = data.model_dump(exclude_unset=True)

            next_article = await self.article_repo.update(
                article=article_db,
                updates=updates
            )

            await self.activity_log.create(
                user_id=user_id,
                target_id=str(next_article.id),
                target_type=TargetType.ARTICLE,
                movement_type=MovementType.ARTICLE_STATUS,
                details=(
                    f"Se modificó el estado del artículo NRO: {next_article.id} "
                    f"de {previous_state} a {next_article.status}"
                ),
            )

            await self.db.refresh(next_article)
            return next_article            

    async def change_category(
        self, 
        data: UpdateCategory, 
        article_id: int, 
        user_id: int
    ) -> Article:
        article_db = await self.exist_article(article_id=article_id)        

        async with self._transaction():
            previous_category = await self.get_category(
                category_id=article_db.category_id
            )

            updates = data.model_dump(exclude_unset=True)

            next_article = await self.article_repo.update(
                article=article_db,
                updates=updates
            )

            next_category = await self.get_category(
                category_id=data.category_id
            )

            await self.activity_log.create(
                user_id=user_id,
                target_id=str(next_article.id),
                target_type=TargetType.ARTICLE,
                movement_type=MovementType.CATEGORY_CHANGE,
                details=(
                    f"Se modificó la categoría del artículo NRO: {next_article.id} "
                    f"de {previous_category} a {next_category}"
                ),
            )

            await self.db.refresh(next_article)
            return next_article

    async def change_brand(
        self, 
        data: UpdateBrand, 
        article_id: int, 
        user_id: int
    ) -> Article:
        article_db = await self.exist_article(article_id=article_id)

        async with self._transaction():
            previous_brand = await self.get_brand(
                brand_id=article_db.brand_id
            )

            updates = data.model_dump(exclude_unset=True)
            
            next_article = await self.article_repo.update(
                article=article_db,
                updates=updates
            )

            next_brand = await self.get_brand(
                brand_id=data.brand_id
            )

            await self.activity_log.create(
                user_id=user_id,
                target_id=str(next_article.id),
                target_type=TargetType.ARTICLE,
                movement_type=MovementType.BRAND_CHANGE,
                details=(
                    f"Se modificó la brand del artículo NRO: {next_article.id} "
                    f"de {previous_brand} a {next_brand}"
                ),
            )

            await self.db.refresh(next_article)
            return next_article

    ######################## FUNCIONES HELPERS #######################
    
    async def exist_title(self, title):
        exists = await self.article_repo.title_exists(title=title)        
        if exists:
            raise ArticleExist()

    async def exist_article(self, article_id: int) -> Article:
        article_db = await self.article_repo.get(
            article_id=article_id
        )             
        if not article_db:
            raise ArticleNotFound()
        return article_db

    async def get_category(self, category_id: int) -> Category:
        category_db = await self.category_repo.get(
            category_id=category_id
        )
        if not category_db:
            raise CategoryNotFound()
        return category_db

    async def get_brand(self, brand_id: int) -> Brand:
        brand_db = await self.brand_repo.get(
            brand_id=brand_id        
        )
        if not brand_db:
            raise BrandNotFound()
        return brand_db