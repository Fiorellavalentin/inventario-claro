-- schema.sql  (referencia — ya ejecutado en Supabase)

create table if not exists equipos (
    id              bigserial primary key,
    imei            text,
    iccid           text,
    marca           text not null,
    modelo          text not null,
    categoria       text not null default 'equipo',   -- equipo | sim | equipo+chip
    fecha_compra    date not null,
    precio_compra   numeric(10,2) not null,
    factura_compra  text,
    estado          text not null default 'stock',    -- stock | vendido
    fecha_venta     date,
    precio_venta    numeric(10,2),
    cliente         text,
    comprobante_venta text,
    estado_nc       text not null default 'no_aplica', -- no_aplica | pendiente | emitida | reclamada
    fecha_limite_nc date,
    fecha_emision_nc date,
    monto_nc        numeric(10,2),
    notas           text,
    created_at      timestamptz not null default now()
);

create table if not exists reclamos (
    id              bigserial primary key,
    equipo_id       bigint references equipos(id),
    imei            text,
    modelo          text,
    motivo          text,
    email_borrador  text,
    estado          text not null default 'pendiente', -- pendiente | enviado | resuelto
    fecha_envio     date not null default current_date,
    fecha_resolucion date,
    created_at      timestamptz not null default now()
);

create table if not exists config (
    id              int primary key default 1,
    distribuidor    text not null default 'Mi distribuidora',
    dias_limite_nc  int  not null default 30
);

-- Insertar fila de configuracion por defecto si no existe
insert into config (id, distribuidor, dias_limite_nc)
values (1, 'Mi distribuidora', 30)
on conflict (id) do nothing;
