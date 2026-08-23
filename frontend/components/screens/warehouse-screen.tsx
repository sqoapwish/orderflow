"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import type {
  Product,
  ProductPage,
  StockBalance,
  StockPage,
  User,
  Warehouse,
  WarehouseList,
} from "@/lib/types";

import { EmptyState, ErrorState, Icon, LoadingBlock, ProductMark } from "../ui";

export function WarehouseScreen({ user }: { user: User | null }) {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [stock, setStock] = useState<StockBalance[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!user || user.role === "customer") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [warehouseData, stockData, productData] = await Promise.all([
        apiRequest<WarehouseList>("/inventory/warehouses"),
        apiRequest<StockPage>("/inventory/stock?page_size=100"),
        apiRequest<ProductPage>("/catalog/products?page_size=100", {}, { auth: false }),
      ]);
      setWarehouses(warehouseData.items);
      setStock(stockData.items);
      setProducts(productData.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить остатки");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const productMap = useMemo(() => new Map(products.map((product) => [product.id, product])), [products]);
  const warehouseMap = useMemo(() => new Map(warehouses.map((warehouse) => [warehouse.id, warehouse])), [warehouses]);
  const totals = stock.reduce(
    (result, item) => ({ onHand: result.onHand + item.on_hand, reserved: result.reserved + item.reserved, available: result.available + item.available }),
    { onHand: 0, reserved: 0, available: 0 },
  );

  if (!user || user.role === "customer") {
    return <div className="page-shell"><EmptyState icon="warehouse" title="Склад доступен менеджеру" text="Операционные остатки защищены ролевой моделью." /></div>;
  }

  return (
    <div className="page-shell">
      <section className="page-heading">
        <div><span className="eyebrow">Управление запасами</span><h1>Склады и остатки</h1><p>Физическое количество, резервы и доступность в одном представлении.</p></div>
      </section>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {loading ? <LoadingBlock label="Загружаем склады" /> : (
        <>
          <section className="inventory-kpis">
            <article className="mini-kpi card"><span className="mini-icon"><Icon name="warehouse" /></span><div><span>Активных складов</span><strong>{warehouses.filter((item) => item.is_active).length}</strong></div></article>
            <article className="mini-kpi card"><span className="mini-icon lavender"><Icon name="box" /></span><div><span>Физический остаток</span><strong>{totals.onHand}</strong></div></article>
            <article className="mini-kpi card"><span className="mini-icon coral"><Icon name="orders" /></span><div><span>В резерве</span><strong>{totals.reserved}</strong></div></article>
            <article className="mini-kpi card"><span className="mini-icon mint"><Icon name="check" /></span><div><span>Доступно</span><strong>{totals.available}</strong></div></article>
          </section>
          <section className="card warehouse-table">
            <div className="card-title"><div><span className="eyebrow">Актуально сейчас</span><h2>Остатки по товарам</h2></div></div>
            {stock.length === 0 ? <EmptyState title="Остатков пока нет" text="Поступления и перемещения появятся здесь автоматически." /> : (
              <>
                <div className="table-head stock-grid"><span>Товар</span><span>Склад</span><span>Физически</span><span>Резерв</span><span>Доступно</span></div>
                {stock.map((item) => {
                  const product = productMap.get(item.product_id);
                  const warehouse = warehouseMap.get(item.warehouse_id);
                  return (
                    <div className="table-row stock-grid" key={item.id}>
                      <div className="table-product"><ProductMark name={product?.name ?? item.product_id} /><div><strong>{product?.name ?? "Неизвестный товар"}</strong><small>{product?.sku ?? item.product_id.slice(0, 8)}</small></div></div>
                      <div><strong>{warehouse?.name ?? "Склад"}</strong><small>{warehouse?.code ?? item.warehouse_id.slice(0, 8)}</small></div>
                      <span>{item.on_hand}</span><span>{item.reserved}</span><strong className={item.available <= 10 ? "low-value" : ""}>{item.available}</strong>
                    </div>
                  );
                })}
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
