-- ============================================================================
-- FVX Backend — Navigation menu (api_menu → api_menusection → api_menuitem)
-- Rutas alineadas con el front (Angular): /dashboard, /users, /groups, /components
-- Iconos: nombres ligature de Google Material Symbols. Catálogo: https://fonts.google.com/icons
-- Idempotente: upsert por slug; mantiene un único is_default.
-- ============================================================================

BEGIN;

-- Solo un menú marcado por defecto.
UPDATE api_menu SET is_default = false WHERE slug IS DISTINCT FROM 'default-navigation';

INSERT INTO api_menu (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    is_default
)
VALUES (
    NOW(),
    NOW(),
    true,
    'MNU-00000001-0001-4001-8001-000000000001',
    'Default navigation',
    'default-navigation',
    '',
    true
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    is_active = true,
    is_default = true,
    description = EXCLUDED.description,
    modified = NOW();

UPDATE api_menu SET is_default = false WHERE slug <> 'default-navigation';
UPDATE api_menu SET is_default = true WHERE slug = 'default-navigation';

-- ─── Section: Home ───
INSERT INTO api_menusection (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    "order",
    menu_id
)
SELECT
    NOW(),
    NOW(),
    true,
    'SEC-00000001-0001-4001-8001-000000000003',
    'Home',
    'home',
    '',
    0,
    m.id
FROM api_menu m
WHERE m.slug = 'default-navigation'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    is_active = true,
    "order" = EXCLUDED."order",
    menu_id = EXCLUDED.menu_id,
    modified = NOW();

INSERT INTO api_menuitem (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    route,
    icon,
    "order",
    allowed_roles,
    section_id
)
SELECT
    NOW(),
    NOW(),
    true,
    'MIT-00000001-0001-4001-8001-000000000004',
    'Dashboard',
    'menu-dashboard',
    '',
    '/dashboard',
    'dashboard',
    10,
    '[]'::jsonb,
    s.id
FROM api_menusection s
WHERE s.slug = 'home'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    route = EXCLUDED.route,
    icon = EXCLUDED.icon,
    "order" = EXCLUDED."order",
    allowed_roles = EXCLUDED.allowed_roles,
    is_active = true,
    section_id = EXCLUDED.section_id,
    modified = NOW();

-- ─── Section: Administration ───
INSERT INTO api_menusection (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    "order",
    menu_id
)
SELECT
    NOW(),
    NOW(),
    true,
    'SEC-00000001-0001-4001-8001-000000000001',
    'Administration',
    'administration',
    '',
    10,
    m.id
FROM api_menu m
WHERE m.slug = 'default-navigation'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    is_active = true,
    "order" = EXCLUDED."order",
    menu_id = EXCLUDED.menu_id,
    modified = NOW();

INSERT INTO api_menuitem (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    route,
    icon,
    "order",
    allowed_roles,
    section_id
)
SELECT
    NOW(),
    NOW(),
    false,
    'MIT-00000001-0001-4001-8001-000000000001',
    'Users',
    'menu-users',
    '',
    '/users',
    'people',
    10,
    '["EDITOR","ADMIN"]'::jsonb,
    s.id
FROM api_menusection s
WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    route = EXCLUDED.route,
    icon = EXCLUDED.icon,
    "order" = EXCLUDED."order",
    allowed_roles = EXCLUDED.allowed_roles,
    is_active = false,
    section_id = EXCLUDED.section_id,
    modified = NOW();

INSERT INTO api_menuitem (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    route,
    icon,
    "order",
    allowed_roles,
    section_id
)
SELECT
    NOW(),
    NOW(),
    false,
    'MIT-00000001-0001-4001-8001-000000000002',
    'Groups',
    'menu-groups',
    '',
    '/groups',
    'group',
    20,
    '["ADMIN"]'::jsonb,
    s.id
FROM api_menusection s
WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    route = EXCLUDED.route,
    icon = EXCLUDED.icon,
    "order" = EXCLUDED."order",
    allowed_roles = EXCLUDED.allowed_roles,
    is_active = false,
    section_id = EXCLUDED.section_id,
    modified = NOW();

-- ─── Administration items: Suscripciones / contenido (FVX) ───
-- Idempotentes (upsert por slug). Rutas SIN /admin: el front antepone /admin
-- (normalizeNavRoute). Iconos = los del fallback de LayoutComponent.
INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-000000000005', 'Plans', 'menu-plans', '', '/plans', 'card_membership', 30, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-000000000006', 'Customers', 'menu-customers', '', '/customers', 'badge', 40, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-000000000007', 'Subscriptions', 'menu-subscriptions', '', '/subscriptions', 'subscriptions', 50, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-000000000008', 'Content', 'menu-content', '', '/content', 'video_library', 60, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-000000000009', 'Programacion', 'menu-programacion', '', '/programacion', 'event_note', 65, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-00000000000a', 'Events', 'menu-events', '', '/events', 'celebration', 70, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

INSERT INTO api_menuitem (created, modified, is_active, uuid, name, slug, description, route, icon, "order", allowed_roles, section_id)
SELECT NOW(), NOW(), true, 'MIT-00000001-0001-4001-8001-00000000000b', 'Messages', 'menu-messages', '', '/messages', 'mail', 80, '["EDITOR","ADMIN"]'::jsonb, s.id
FROM api_menusection s WHERE s.slug = 'administration'
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, route = EXCLUDED.route, icon = EXCLUDED.icon, "order" = EXCLUDED."order", allowed_roles = EXCLUDED.allowed_roles, is_active = true, section_id = EXCLUDED.section_id, modified = NOW();

-- ─── Section: Dev (sample feature gallery) ───
INSERT INTO api_menusection (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    "order",
    menu_id
)
SELECT
    NOW(),
    NOW(),
    true,
    'SEC-00000001-0001-4001-8001-000000000002',
    'Dev',
    'dev',
    '',
    90,
    m.id
FROM api_menu m
WHERE m.slug = 'default-navigation'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    is_active = true,
    "order" = EXCLUDED."order",
    menu_id = EXCLUDED.menu_id,
    modified = NOW();

INSERT INTO api_menuitem (
    created,
    modified,
    is_active,
    uuid,
    name,
    slug,
    description,
    route,
    icon,
    "order",
    allowed_roles,
    section_id
)
SELECT
    NOW(),
    NOW(),
    true,
    'MIT-00000001-0001-4001-8001-000000000003',
    'Components',
    'menu-components',
    '',
    '/components',
    'widgets',
    10,
    '[]'::jsonb,
    s.id
FROM api_menusection s
WHERE s.slug = 'dev'
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    route = EXCLUDED.route,
    icon = EXCLUDED.icon,
    "order" = EXCLUDED."order",
    allowed_roles = EXCLUDED.allowed_roles,
    is_active = true,
    section_id = EXCLUDED.section_id,
    modified = NOW();

COMMIT;
