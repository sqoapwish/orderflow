export type UserRole = "customer" | "manager" | "admin";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthResponse {
  user: User;
  tokens: TokenPair;
}

export interface Product {
  id: string;
  category_id: string;
  name: string;
  slug: string;
  sku: string;
  description: string | null;
  price_minor: number;
  currency: string;
  image_url: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductPage {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ProductAvailability {
  warehouse_id: string;
  warehouse_name: string;
  warehouse_code: string;
  available: number;
}

export interface ProductAvailabilityList {
  items: ProductAvailability[];
  total: number;
}

export interface CartItem {
  id: string;
  product_id: string;
  warehouse_id: string;
  product_name: string;
  product_sku: string;
  unit_price_minor: number;
  quantity: number;
  line_total_minor: number;
  currency: string;
  is_available: boolean;
  created_at: string;
  updated_at: string;
}

export interface Cart {
  id: string | null;
  items: CartItem[];
  total_minor: number | null;
  currency: string | null;
  updated_at: string | null;
}

export type OrderStatus =
  | "pending_payment"
  | "paid"
  | "payment_failed"
  | "cancelled"
  | "refunded";

export interface OrderItem {
  id: string;
  product_id: string;
  warehouse_id: string;
  product_name: string;
  product_sku: string;
  unit_price_minor: number;
  quantity: number;
  line_total_minor: number;
  currency: string;
}

export interface Order {
  id: string;
  order_number: string;
  customer_id: string;
  status: OrderStatus;
  total_minor: number;
  currency: string;
  items: OrderItem[];
  created_at: string;
  updated_at: string;
}

export interface OrderPage {
  items: Order[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type PaymentStatus = "pending" | "succeeded" | "failed" | "cancelled" | "refunded";

export interface Payment {
  id: string;
  order_id: string;
  customer_id: string;
  provider: string;
  provider_payment_id: string;
  checkout_url: string;
  status: PaymentStatus;
  amount_minor: number;
  currency: string;
  failure_code: string | null;
  expires_at: string;
  processed_at: string | null;
  created_at: string;
}

export interface AnalyticsPeriod {
  date_from: string;
  date_to: string;
}

export interface CurrencySales {
  currency: string;
  paid_orders: number;
  gross_revenue_minor: number;
  failed_payments: number;
  refunded_payments: number;
  refunded_amount_minor: number;
  net_revenue_minor: number;
}

export interface DailySales extends CurrencySales {
  day: string;
}

export interface SalesAnalytics {
  period: AnalyticsPeriod;
  currencies: CurrencySales[];
  daily: DailySales[];
}

export interface TopProduct {
  product_id: string;
  product_name: string;
  product_sku: string;
  currency: string;
  paid_quantity: number;
  gross_revenue_minor: number;
  paid_orders: number;
}

export interface TopProducts {
  period: AnalyticsPeriod;
  items: TopProduct[];
}

export interface LowStockItem {
  warehouse_id: string;
  warehouse_name: string;
  warehouse_code: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  on_hand: number;
  reserved: number;
  available: number;
}

export interface LowStockPage {
  items: LowStockItem[];
  threshold: number;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface Warehouse {
  id: string;
  name: string;
  code: string;
  location: string | null;
  is_active: boolean;
}

export interface WarehouseList {
  items: Warehouse[];
  total: number;
}

export interface StockBalance {
  id: string;
  warehouse_id: string;
  product_id: string;
  on_hand: number;
  reserved: number;
  available: number;
}

export interface StockPage {
  items: StockBalance[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AuditEvent {
  id: string;
  action: string;
  actor_type: "user" | "system";
  actor_id: string | null;
  actor_role: UserRole | null;
  resource_type: string;
  resource_id: string;
  correlation_id: string | null;
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface AuditPage {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
