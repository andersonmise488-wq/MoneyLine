PUBLIC_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    #MainMenu, footer, header[data-testid="stHeader"] {
        visibility: hidden;
    }

    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 3rem;
        max-width: 960px;
    }

    .moneyline-hero {
        background: linear-gradient(145deg, #0c1222 0%, #0f2a1f 45%, #071510 100%);
        border-radius: 20px;
        padding: 2.5rem 2.4rem;
        color: #ecfdf5;
        margin-bottom: 2rem;
        border: 1px solid rgba(34, 197, 94, 0.2);
        box-shadow: 0 24px 48px rgba(0, 0, 0, 0.35);
    }

    .moneyline-hero h1 {
        color: #f0fdf4;
        font-size: 2.35rem;
        font-weight: 700;
        margin: 0 0 0.6rem 0;
        letter-spacing: -0.02em;
    }

    .moneyline-hero .tagline {
        color: #86efac;
        font-size: 1.15rem;
        margin: 0 0 1.4rem 0;
        line-height: 1.5;
    }

    .hero-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
    }

    .hero-pill {
        background: rgba(34, 197, 94, 0.12);
        border: 1px solid rgba(34, 197, 94, 0.35);
        color: #bbf7d0;
        padding: 0.35rem 0.85rem;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 500;
    }

    .feature-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 1rem;
        margin: 0 0 2rem 0;
    }

    @media (max-width: 768px) {
        .feature-grid { grid-template-columns: 1fr; }
    }

    .feature-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 1.25rem 1.3rem;
    }

    .feature-card .icon {
        font-size: 1.5rem;
        margin-bottom: 0.5rem;
    }

    .feature-card h3 {
        color: #f9fafb;
        font-size: 1rem;
        margin: 0 0 0.35rem 0;
    }

    .feature-card p {
        color: #9ca3af;
        font-size: 0.88rem;
        margin: 0;
        line-height: 1.45;
    }

    .section-title {
        color: #f9fafb;
        font-size: 1.15rem;
        font-weight: 600;
        margin: 0 0 0.75rem 0;
    }

    .teaser-box {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 2rem;
    }

    .teaser-box p {
        color: #94a3b8;
        font-size: 0.9rem;
        margin: 0 0 0.75rem 0;
    }

    .teaser-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.65rem 0;
        border-bottom: 1px solid #1e293b;
        color: #e2e8f0;
        font-size: 0.92rem;
    }

    .teaser-row:last-child { border-bottom: none; }

    .teaser-margin {
        color: #4ade80;
        font-weight: 600;
        font-size: 0.88rem;
    }

    .pricing-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 1rem;
        margin: 0 0 2rem 0;
    }

    @media (max-width: 640px) {
        .pricing-grid { grid-template-columns: 1fr; }
    }

    .price-card {
        background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
        border: 1px solid #374151;
        border-radius: 14px;
        padding: 1.4rem 1.5rem;
        text-align: center;
    }

    .price-card.featured {
        border-color: #22c55e;
        box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.25);
    }

    .price-card .plan {
        color: #9ca3af;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.35rem;
    }

    .price-card .amount {
        color: #f0fdf4;
        font-size: 1.75rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }

    .price-card .period {
        color: #6b7280;
        font-size: 0.85rem;
    }

    .cta-block {
        background: #052e16;
        border: 1px solid #166534;
        border-radius: 16px;
        padding: 1.6rem 1.8rem;
        text-align: center;
        margin-bottom: 2rem;
    }

    .cta-block h3 {
        color: #4ade80;
        margin: 0 0 0.4rem 0;
        font-size: 1.2rem;
    }

    .cta-block p {
        color: #bbf7d0;
        margin: 0 0 1rem 0;
        font-size: 0.95rem;
    }

    .staff-login {
        margin-top: 2.5rem;
        padding-top: 1.5rem;
        border-top: 1px solid #1f2937;
    }

    .admin-badge {
        display: inline-block;
        background: #7c2d12;
        color: #ffedd5;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.04em;
    }

    div[data-testid="stMetric"] {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 0.6rem;
    }
</style>
"""
