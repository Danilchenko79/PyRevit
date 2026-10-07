# -*- coding: utf-8 -*-
"""Настройки расчёта грузовых площадей. Все длины — мм, нагрузка — кН/м²."""

DEFAULTS = {
    'k_zone': 1.5,        # зона угла/торца стены вдоль полки = k·d_m (от грани пересекающей стены)
    'c_nom': 25.0,        # защитный слой, мм (как в calc-punching-shear-v6)
    'bar_d': 12.0,        # диаметр верхних стержней, мм: d_m = h - c_nom - bar_d
    'edge_k': 2.0,        # грань колонны ближе edge_k·d_m к краю плиты -> «у края» (u1 режется краем)
    'opening_k': 6.0,     # проём ближе opening_k·d_m -> флаг (ת"י 466 / EC2 6.4.2(3))
    'pylon_ratio': 4.0,   # свободная стена с L <= pylon_ratio·t считается пилоном (колонной)
    'grid_mm': 100.0,     # шаг растра
    'q_d': 0.0,           # расчётная нагрузка на плиту, кН/м² (0 -> V_d не считается)
    'node_tol': 20.0,     # допуск стыковки осей стен, мм
    'min_angle': 15.0,    # стены с углом меньше — продолжение друг друга, а не угол, град
    'z_tol': 50.0,        # допуск по высоте «опора доходит до низа плиты», мм
    'link_mask': u'-ST-', # колонны/стены берутся из связей, в имени которых есть эта строка
    'use_beams': 1.0,     # 1 — балки выше толщины плиты (прямые и обратные) — линейные опоры
    # начальные значения для HTML-схемы (там меняются на лету, по плитам)
    'g_add': 0.0,         # постоянная сверх собственного веса (полы, перегородки), кН/м²
    'q_live': 0.0,        # полезная, кН/м²
    'gamma_g': 1.4,       # ת"י 412 (решение пользователя 07.10.2026)
    'gamma_q': 1.6,
    # проверка продавливания по Excel компании (check.py); в схеме — общие + правка по точке
    'fck': 30.0,          # МПа (в формулах 0.7·fck, как в ת"י 466)
    'top_d1': 0.0,        # Ø1 верхних стержней над опорой, мм (0 -> bar_d)
    'top_s1': 200.0,      # шаг Ø1, мм
    'top_d2': 0.0,        # Ø2 добавочных, мм (0 -> нет)
    'top_s2': 200.0,      # шаг Ø2, мм
    'sigma_cp': 0.0,      # обжатие, МПа
    'sr': 0.0,            # шаг периметров хомутов, мм (0 -> 0.75·d_m)
    'alpha_w': 90.0,      # наклон хомутов, град
    'alpha_b': 45.0,      # наклон отгибов, град
}

# β по типу опоры. Колонна/пилон — как в calc-punching-shear-v6 (col-int/edge/corner),
# угол L — как в calc-punching-wall-corner_v2. Торец и узлы T/X — ПО УМОЛЧАНИЮ, подтвердить.
BETA = {
    'column:int': 1.15,
    'column:edge': 1.40,
    'column:corner': 1.50,
    'pylon:int': 1.15,
    'pylon:edge': 1.40,
    'pylon:corner': 1.50,
    'wall_L': 1.50,
    'wall_T': 1.15,
    'wall_X': 1.15,
    'wall_end': 1.40,
}


def merged(user=None):
    """DEFAULTS + пользовательские значения (неизвестные ключи игнорируются)."""
    p = dict(DEFAULTS)
    p['beta'] = dict(BETA)
    if user:
        for k, v in user.items():
            if k == 'beta' and isinstance(v, dict):
                p['beta'].update(v)
            elif k in DEFAULTS and v is not None:
                p[k] = v if isinstance(DEFAULTS[k], type(u'')) else float(v)
    validate(p)
    return p


def validate(p):
    for k in ('k_zone', 'edge_k', 'opening_k', 'pylon_ratio', 'grid_mm'):
        if p[k] <= 0:
            raise ValueError(u'{} must be > 0'.format(k))
    if p['grid_mm'] < 20 or p['grid_mm'] > 500:
        raise ValueError(u'grid_mm outside 20..500 mm')
    if p['q_d'] < 0:
        raise ValueError(u'q_d < 0')
    if not 10 <= p['fck'] <= 100:
        raise ValueError(u'fck outside 10..100 MPa')
    if p['top_s1'] <= 0 or p['top_s2'] <= 0:
        raise ValueError(u'bar spacing must be > 0')


def d_m(h, p):
    """Средняя рабочая высота, мм."""
    return max(h - p['c_nom'] - p['bar_d'], 0.3 * h)
