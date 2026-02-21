# Inventory Page Redesign Plan
**Sprint: Inventory UI Alignment**
**Document Date:** 2026-02-20

---

## 1. Executive Summary

The `/inventory/` page currently uses an **outdated design language** inconsistent with the rest of the application. While pages like Purchase, Sales, Receivables, and Returns follow a polished, modern design system (large headings, two-column layout with a sticky right panel, card-based list rows, `rounded-[2rem]` containers, animated HTMX partials), the Inventory page uses a generic, flat Tailwind table layout with none of these conventions. Additionally, it contains **literal string rendering bugs** due to a missing `{% load humanize %}` tag and an incorrect Alpine.js active-tab expression.

This document catalogues all gaps and defines the redesign plan.

---

## 2. Design Persona of the Application (Reference Standard)

Derived from analysing `purchase_list.html`, `sales_list.html`, `receivables_dashboard.html`, and `returns_list.html`.

### 2.1 Layout Structure
- **Two-column layout** at `xl` breakpoints: a wide main content column (`flex-1 min-w-0`) on the left and a sticky right panel (`xl:w-[400px]` or `w-4/12`) on the right.
- The main area uses generous padding: `p-6 md:p-10 lg:p-12`.
- Top-level container is `flex flex-col xl:flex-row min-h-screen`.
- Each page's right panel contains contextual financial stats with gradient cards.

### 2.2 Page Header
- Breadcrumb chip: a small `<span>` with colored badge (e.g. `bg-blue-50 text-blue-600`, `bg-green-50 text-green-600`) followed by section label in `text-gray-400`.
- Page title: `text-4xl md:text-5xl font-bold text-gray-900 tracking-tight` (very large, bold).
- Total values or search/action controls sit inline with the title row.

### 2.3 Search Bar
- Positioned inline right of the page title.
- Has an embedded SVG search icon via `absolute left-4 top-1/2 -translate-y-1/2`.
- Input styling: `bg-white border-2 border-gray-100 focus:border-[color]-500/20 rounded-xl py-3 pl-12 pr-4 font-medium`.
- Focus accent color matches the page theme.

### 2.4 List Cards (replacing Tables)
- Each data row is rendered as an individual **card** (`bg-white rounded-2xl p-5 border border-gray-100`).
- Cards have hover effects: `hover:border-[theme-color]-200 hover:shadow-lg transition-all duration-200`.
- Cards use a **date box** accent: a `w-16 h-16` square with themed background (`bg-blue-50`, `bg-green-50`, `bg-amber-50`) showing month and day prominently.
- Card body uses a fluid grid (`grid-cols-2 md:grid-cols-4`) for multi-column data.
- Action buttons (view/delete) are hidden by default and revealed on hover via `opacity-0 group-hover:opacity-100 transition-opacity`.

### 2.5 Status Pills / Badges
- Rounded-full pills: `inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold`.
- Always include a colored dot: `w-1.5 h-1.5 rounded-full bg-[color]-500`.
- Colors: green (good/paid), amber (warning/partial), red (danger/expired/out).

### 2.6 Right Panel (Sticky Stats)
- `bg-white border-l border-gray-100`, sticky at `xl` breakpoints.
- Contains a **hero gradient card** (`bg-gradient-to-br`, `rounded-[2rem]`, `shadow-xl`) with the primary KPI.
- Below it: secondary cards for sub-metrics.
- At bottom: a timeline or ranked list of recent activity.

### 2.7 Empty States
- `text-center py-20 bg-white rounded-[2.5rem] border-2 border-dashed border-gray-100`.
- Icon in a `w-16 h-16 bg-gray-50 rounded-2xl` container.
- Bold heading + descriptive paragraph.

### 2.8 Pagination
- Inline `Prev` / `Next` buttons styled `bg-slate-800 text-white rounded-l / rounded-r` is acceptable, but should be elevated to match card style or use text links.

### 2.9 Typography
- Font: **Inter** (loaded via Google Fonts in `base.html`).
- `{% load humanize %}` is always loaded for `|intcomma`.
- Amounts always use `₹` prefix or `&#8377;` and pipe through `|intcomma`.

### 2.10 Color Theme per Section
| Section     | Accent Color | Badge BG       |
|-------------|--------------|----------------|
| Inventory   | **Blue**     | `bg-blue-50`   |
| Purchase    | Blue         | `bg-blue-50`   |
| Sales       | Green        | `bg-green-50`  |
| Returns     | Amber / Red  | `bg-amber-50`  |
| Receivables | Purple       | `bg-purple-100`|

Inventory's theme colour is **Blue** (consistent with its purchase-related nature).

---

## 3. Current Inventory Page — Audit & Gaps

### 3.1 Layout Gap (Critical)
| What | Current | Required |
|------|---------|---------|
| Layout | Single-column `max-w-7xl mx-auto` with no right panel | Two-column `flex flex-col xl:flex-row` with sticky right stats panel |
| Main padding | `max-w-7xl mx-auto` (no padding) | `p-6 md:p-10 lg:p-12` on `<main>` |

### 3.2 Header Gap (Critical)
| What | Current | Required |
|------|---------|---------|
| Breadcrumb | None | `Inventory / Stock Ledger` breadcrumb chip |
| Title | `text-3xl font-bold text-slate-800` | `text-4xl md:text-5xl font-bold text-gray-900 tracking-tight` |
| Stock Value Widget | Floating blue box (detached from standard patterns) | Right panel hero card |

### 3.3 Search & Filters Gap (Moderate)
| What | Current | Required |
|------|---------|---------|
| Search | Separate `bg-white p-4 rounded-lg shadow mb-6` box | Inline in header row with embedded icon (same as Purchase/Sales) |
| Filter tabs | `px-4 py-2 rounded-full` anchors with manual class | Alpine.js tab switcher matching Returns page (`bg-white p-1.5 rounded-2xl border inline-flex`) |
| Active tab logic | `'{{ status }}' == 'None'` — **BROKEN** (always false due to Python `None` being a string in template) | Use `?status` query param approach with proper Django `{% if not status %}` logic |

### 3.4 Table vs Cards Gap (Critical)
| What | Current | Required |
|------|---------|---------|
| Data display | HTML `<table>` with `<thead>` and `<tbody>` rows | Individual `bg-white rounded-2xl` cards per batch row |
| Row hover | `hover:bg-gray-50` on `<tr>` | Full card border glow + shadow on hover (`hover:border-blue-200 hover:shadow-lg`) |
| Category display | Plain text cell | Small rounded badge |
| Stock status | Badge only on quantity | Status pill with colored dot (Green/Amber/Red) matching app standard |
| Action buttons | None (no view/edit link on row) | Hover-reveal icon buttons for detail/action |

### 3.5 Right Panel Missing (Critical)
The Inventory page has **no right panel**. The app standard mandates a right panel with:
- A gradient hero card showing **Total Stock Value** (the KPI currently awkwardly placed in the header)
- A secondary card: **Low Stock Count** (items below 10 units)
- A secondary card: **Expiring Soon Count** (items expiring within 30 days)
- A ranked list of **Top Categories by Value**

### 3.6 Literal String / Template Issues (Bugs)

#### Bug 1 — Missing `{% load humanize %}`
**File:** `inventory/inventory_list.html` and `inventory/partials/inventory_table.html`
**Problem:** `total_stock_value` and `batch.stock_value` are rendered without `|intcomma`. Large numbers like `₹1234567` display without comma formatting (e.g. should be `₹12,34,567`).
**Fix:** Add `{% load humanize %}` at top of both templates and pipe all monetary values through `|intcomma`.

#### Bug 2 — Broken Active Tab Expression
**File:** `inventory/inventory_list.html`, line 41
**Current Code:**
```html
:class="{ 'bg-blue-600 text-white hover:bg-blue-700': '{{ status }}' == 'None' }"
```
**Problem:** Django renders Python `None` as the literal string `"None"`. The Alpine.js expression compares a JS string to `'None'` — this works only coincidentally and fails when `status` is empty string or null. The `Low Stock` and `Expired` tabs have no active state at all. This means the UI never clearly shows which filter is active.
**Fix:** Drive active tab state from the URL using a proper server-side approach with `{% if not status %}`, `{% if status == 'low' %}`, `{% if status == 'expired' %}` applied as `{% if %}...{% endif %}` class conditionals directly in the Django template (same approach used across other pages in the app).

#### Bug 3 — Hardcoded `px-2.5 py-0.5` Badges Not Matching App Standard
**File:** `inventory/partials/inventory_table.html`, lines 42–50
**Problem:** Stock quantity badges use `px-2.5 py-0.5 rounded` which is the old Bootstrap-style badge, not the pill standard (`inline-flex items-center gap-1.5 px-3 py-1 rounded-full`) used everywhere else.
**Fix:** Redesign as standard pills with colored dot.

---

## 4. Redesign Plan

### 4.1 `inventory/inventory_list.html` — Full Rewrite

**New Structure:**
```
<div class="flex flex-col xl:flex-row min-h-screen bg-[#F8F9FA]">

  <!-- LEFT: Main Content -->
  <main class="flex-1 min-w-0 p-6 md:p-10 lg:p-12 pb-32 xl:pb-12">
    <div class="max-w-5xl mx-auto space-y-10">

      <!-- Header -->
      <header>
        <!-- Breadcrumb chip: "Inventory" badge -->
        <!-- Title: "Stock Ledger" at text-4xl md:text-5xl -->
        <!-- Inline search bar (embedded icon, rounded-xl) -->
      </header>

      <!-- Filter Tab Switcher (Alpine-free, URL-driven) -->
      <!-- Tabs: All | Low Stock | Expired | Out of Stock -->
      <!-- Active state driven by Django {% if status == 'low' %} etc. -->

      <!-- HTMX Target: the card list -->
      <div id="inventory-table">
        {% include 'inventory/partials/inventory_table.html' %}
      </div>

    </div>
  </main>

  <!-- RIGHT: Sticky Stats Panel -->
  <aside class="xl:w-[400px] bg-white border-l border-gray-100">
    <div class="xl:fixed xl:w-[400px] h-full flex flex-col pt-10 border-l border-gray-100 bg-white">

      <!-- Panel Title -->
      <div class="p-8 pb-4 border-b border-gray-50 hidden xl:block">
        <h2>Stock Overview</h2>
        <p>Live inventory snapshot.</p>
      </div>

      <div class="flex-1 p-8 space-y-8 overflow-y-auto">

        <!-- Hero Card: Total Stock Value -->
        <div class="bg-gray-900 text-white rounded-[2rem] p-6 shadow-xl ...">
          Total Stock Value (All Items)
          ₹{{ total_stock_value|intcomma }}
          [Count of batches]
        </div>

        <!-- Secondary Card: Low Stock Alert -->
        <div class="bg-amber-50 rounded-2xl p-5 border border-amber-100">
          Low Stock: [count] batches
        </div>

        <!-- Secondary Card: Expiring Soon -->
        <div class="bg-red-50 rounded-2xl p-5 border border-red-100">
          Expiring in 30 days: [count] batches
        </div>

        <!-- Top Categories by Value (ranked list) -->
        <div>
          Top Categories
          [for each category: rank circle, name, value]
        </div>

      </div>
    </div>
  </aside>

</div>
```

**New Context Variables needed from view (additions):**
- `low_stock_count` — batches with `current_quantity < 10 AND > 0`
- `expiring_soon_count` — batches with `expiry_date <= today + 30 days`
- `out_of_stock_count` — batches with `current_quantity == 0`
- `top_categories` — top 5 categories by summed stock value

### 4.2 `inventory/partials/inventory_table.html` — Full Rewrite

**Old:** Plain HTML `<table>` rows.
**New:** List of `bg-white rounded-2xl` cards. One card per batch.

**Card anatomy (per row):**
```
[Category Badge] | [Product Name + Batch Number] | [Expiry Pill] | [MRP / Sell] | [Stock Qty Pill] | [Stock Value] | [Action Buttons on hover]
```

**Card layout:**
```html
<div class="group bg-white rounded-2xl p-5 border border-gray-100
            hover:border-blue-200 hover:shadow-lg transition-all duration-200
            flex flex-col md:flex-row items-center gap-6">

  <!-- Left: Product Info -->
  <div class="flex-1 min-w-0 grid grid-cols-2 md:grid-cols-4 gap-4 items-center">

    <!-- Col 1: Product + Batch -->
    <div class="col-span-2 md:col-span-1">
      <div class="font-bold text-gray-900">{{ batch.product.name }}</div>
      <div class="text-xs text-gray-400">Batch: {{ batch.batch_number }}</div>
      <span class="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded font-bold">
        {{ batch.product.category.name|default:"Uncategorised" }}
      </span>
    </div>

    <!-- Col 2: Expiry -->
    <div>
      [Expiry pill — red if expired, orange if <= 30d, green otherwise]
    </div>

    <!-- Col 3: Pricing -->
    <div>
      <div class="text-sm font-bold text-gray-900">₹{{ batch.mrp|intcomma }}</div>
      <div class="text-xs text-blue-600 font-bold">Sell: ₹{{ batch.base_selling_price|intcomma }}</div>
    </div>

    <!-- Col 4: Stock + Value -->
    <div>
      [Stock pill: green / amber / gray]
      <div class="text-sm font-bold text-gray-700 mt-1">₹{{ batch.stock_value|intcomma }}</div>
    </div>

  </div>

  <!-- Right: Action Buttons (hover-reveal) -->
  <div class="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2">
    [View/navigate icon if detail page exists]
  </div>

</div>
```

**Empty State:**
```html
<div class="text-center py-20 bg-white rounded-[2.5rem] border-2 border-dashed border-gray-100">
  [Icon] No stock found.
</div>
```

**Pagination:** Keep HTMX pagination but style Prev/Next as outlined `rounded-xl` text buttons.

### 4.3 `inventory/views.py` — Context Additions

Add these to the context dictionary:
```python
from django.db.models import Count
import datetime

today = timezone.now().date()
expiry_threshold = today + datetime.timedelta(days=30)

low_stock_count = Batch.objects.filter(current_quantity__gt=0, current_quantity__lt=10).count()
expiring_soon_count = Batch.objects.filter(expiry_date__lte=expiry_threshold, expiry_date__gte=today).count()
out_of_stock_count = Batch.objects.filter(current_quantity=0).count()

# Top categories by value
from django.db.models import Sum, F
top_categories = (
    Batch.objects
    .values('product__category__name')
    .annotate(total_value=Sum(F('current_quantity') * F('purchase_price')))
    .order_by('-total_value')[:5]
)
```

---

## 5. Bug Fix Summary Table

| # | File | Line(s) | Bug | Fix |
|---|------|---------|-----|-----|
| 1 | `inventory_list.html` | Top | Missing `{% load humanize %}` | Add `{% load humanize %}` |
| 2 | `inventory_table.html` | Top | Missing `{% load humanize %}` | Add `{% load humanize %}` |
| 3 | `inventory_list.html` | 20 | `{{ total_stock_value }}` not comma-formatted | `{{ total_stock_value|intcomma }}` |
| 4 | `inventory_table.html` | 37–38, 53 | `batch.mrp`, `batch.base_selling_price`, `batch.stock_value` not formatted | Add `|intcomma` to each |
| 5 | `inventory_list.html` | 41 | `'{{ status }}' == 'None'` — broken Alpine comparison | Replace with Django-side `{% if not status %}active{% endif %}` class |
| 6 | `inventory_table.html` | 42–50 | Old badge pattern (`px-2.5 py-0.5 rounded`) | Upgrade to pill standard (`inline-flex gap-1.5 rounded-full` with dot) |

---

## 6. Implementation Checklist

- [ ] **Step 1:** Update `inventory/views.py` — add 4 new context variables (`low_stock_count`, `expiring_soon_count`, `out_of_stock_count`, `top_categories`)
- [ ] **Step 2:** Rewrite `inventory/inventory_list.html` — two-column layout, new header, filter tabs, sticky right panel with 3 stat cards + top categories
- [ ] **Step 3:** Rewrite `inventory/partials/inventory_table.html` — card-based rows, standard pills, `{% load humanize %}`, `|intcomma` on all amounts, standard empty state
- [ ] **Step 4:** Verify in browser — confirm no literal tags, confirm stats panel shows correct values, confirm filter tabs highlight correctly, confirm pagination works via HTMX

---

## 7. Design Accent Color for Inventory

Following the app's color convention, the Inventory page uses **Blue** as its accent (`bg-blue-50`, `text-blue-600`, `border-blue-100`, `hover:border-blue-200`), consistent with how it was originally started and consistent with Purchase (also blue-flavored as both deal with stock inflow/management).

The right panel hero card will use `bg-gray-900 text-white` (matching the Purchase page hero card) to keep the premium gray-800/900 feel for the top KPI.

---

*End of Document*
