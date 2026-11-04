-- 새 Supabase 프로젝트의 SQL Editor에서 한 번 실행하세요.
-- 전체 테이블 생성을 하나의 작업으로 묶습니다.
begin;

-- 회원: 비밀번호 원문 대신 bcrypt로 만든 해시만 저장합니다.
create table public.users (
    id bigint generated always as identity primary key,
    email text not null unique,
    password_hash text not null,
    name text not null check (char_length(trim(name)) between 1 and 50),
    created_at timestamptz not null default now(),
    -- 가입할 때 이메일을 소문자로 바꿔 중복 가입을 방지합니다.
    constraint users_email_normalized check (email = lower(trim(email)) and email <> '')
);

-- 상품: 가격은 원 단위의 정수로 저장합니다.
create table public.products (
    id bigint generated always as identity primary key,
    name text not null check (char_length(trim(name)) > 0),
    description text not null default '',
    price integer not null check (price >= 0),
    created_at timestamptz not null default now()
);

-- 주문: 장바구니도 하나의 주문으로 관리합니다.
create table public.orders (
    id bigint generated always as identity primary key,
    user_id bigint not null references public.users(id) on delete cascade,
    status text not null default 'cart'
        check (status in ('cart', 'pending', 'paid')),
    created_at timestamptz not null default now()
);

-- 한 회원에게 장바구니 상태의 주문은 하나만 허용합니다.
create unique index orders_one_cart_per_user
    on public.orders(user_id) where status = 'cart';

-- 회원별 장바구니와 구매내역을 찾을 때 사용합니다.
create index orders_user_id_idx on public.orders(user_id);

-- 주문 상세: 한 주문에 여러 상품과 각각의 수량을 저장합니다.
create table public.order_items (
    id bigint generated always as identity primary key,
    order_id bigint not null references public.orders(id) on delete cascade,
    product_id bigint not null references public.products(id) on delete restrict,
    quantity integer not null check (quantity > 0),
    -- 장바구니에 담은 시점의 가격을 보관합니다.
    -- 금액은 브라우저가 보낸 값을 믿지 않고 서버에서 상품 가격으로 정합니다.
    unit_price integer not null check (unit_price >= 0),
    constraint order_items_order_product_unique unique (order_id, product_id)
);

-- 결제: 결제 성공 시에만 기록을 만들며, 주문당 최대 하나입니다.
create table public.payments (
    id bigint generated always as identity primary key,
    order_id bigint not null unique references public.orders(id) on delete cascade,
    -- 주문 상세의 수량 × 단가를 서버/DB에서 합산해 저장합니다.
    amount bigint not null check (amount >= 0),
    method text not null default 'mock' check (method = 'mock'),
    paid_at timestamptz not null default now()
);

-- 공개 키로는 테이블을 직접 읽거나 수정하지 못하게 합니다.
-- FastAPI 서버만 .env의 service_role 키로 DB에 접근합니다.
alter table public.users enable row level security;
alter table public.products enable row level security;
alter table public.orders enable row level security;
alter table public.order_items enable row level security;
alter table public.payments enable row level security;

revoke all on table public.users, public.products, public.orders,
    public.order_items, public.payments from anon, authenticated;
grant all on table public.users, public.products, public.orders,
    public.order_items, public.payments to service_role;
grant usage, select on sequence public.users_id_seq, public.products_id_seq,
    public.orders_id_seq, public.order_items_id_seq, public.payments_id_seq
    to service_role;

commit;
