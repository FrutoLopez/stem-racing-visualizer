"""CSS styles and UI styling utilities for STEM Racing Visualizer.
Strictly adheres to official STEM Racing Brand Guidelines (V1.3 - March 2026):
- Core Palette: Carbon Shadow (#05000B), Pitlane Pink (#E6007E)
- Supporting CFD Palette: Chicane Violet (#961B81), Turbo Verde (#008A3F), Ignite Indigo (#312783),
  Grid Lime (#95C11F), Apex Glacier (#005CA9), Podium Gold (#FCBC00), Aero Sky (#009FE3), Burnout Orange (#ED6D05)
- Typography: Display headings in Italic Montserrat / Magistral
"""

import base64
from io import BytesIO
import os

try:
    from PIL import Image
except ImportError:
    Image = None

# ==============================================================================
# OFFICIAL STEM RACING BRAND CONSTANTS (V1.3 Brand Guidelines)
# ==============================================================================
CARBON_SHADOW = "#05000B"       # Core background (Pantone Black 6C)
PITLANE_PINK = "#E6007E"        # Core brand accent (Pantone Mag C)
CHICANE_VIOLET = "#961B81"      # Secondary accent (Pantone 2415C)
TURBO_VERDE = "#008A3F"         # Green accent (Pantone 348C)
IGNITE_INDIGO = "#312783"       # Deep Indigo (Pantone 2735C)
GRID_LIME = "#95C11F"           # Vibrant Lime (Pantone 376C)
APEX_GLACIER = "#005CA9"        # Deep Glacier Blue (Pantone 2728C)
PODIUM_GOLD = "#FCBC00"         # Gold Champion (Pantone 4708C)
AERO_SKY = "#009FE3"            # Technical Cyan / Sky Blue (Pantone Cyan C)
BURNOUT_ORANGE = "#ED6D05"      # Energy Orange (Pantone 151C)

CARBON_SHADOW_TINT = "rgba(18, 14, 28, 0.88)"
CARD_BORDER_PINK = "rgba(230, 0, 126, 0.40)"
CARD_BORDER_CYAN = "rgba(0, 159, 227, 0.40)"
CARD_BORDER_ORANGE = "rgba(237, 109, 5, 0.40)"


def get_base64_encoded_image(image_path: str, max_size: tuple = (360, 180)) -> str:
    """Read a local image, optionally downscale in memory to reduce DOM/WebSocket memory, and return base64 string."""
    if os.path.exists(image_path):
        try:
            if Image is not None and max_size:
                with Image.open(image_path) as img:
                    if img.width > max_size[0] or img.height > max_size[1]:
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                        buf = BytesIO()
                        img.save(buf, format="PNG", optimize=True)
                        return base64.b64encode(buf.getvalue()).decode()
            with open(image_path, "rb") as f:
                data = f.read()
            return base64.b64encode(data).decode()
        except Exception:
            return ""
    return ""


def inject_custom_css() -> str:
    """Inject global CSS with Montserrat typography and official STEM Racing dark CFD aesthetic."""
    css = """<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,700;1,800;1,900&display=swap');

html, body, [class*="css"] {
    font-family: 'Montserrat', sans-serif !important;
}

/* Typography Guidelines: Display headings italic */
h1, h2, h3, .sr-header-title, .sr-heading {
    font-family: 'Montserrat', sans-serif !important;
    font-style: italic !important;
    font-weight: 800 !important;
}

/* Overall Background and Theme: Carbon Shadow #05000B with CFD Gradients & Subtle Aerodynamic Pattern */
.stApp {
    background-color: #05000B !important;
    background-image: 
        radial-gradient(circle at 15% 15%, rgba(49, 39, 131, 0.28) 0%, transparent 45%),
        radial-gradient(circle at 85% 85%, rgba(237, 109, 5, 0.20) 0%, transparent 45%),
        radial-gradient(circle at 50% 50%, rgba(230, 0, 126, 0.10) 0%, transparent 60%),
        repeating-linear-gradient(45deg, rgba(230, 0, 126, 0.015) 0px, rgba(230, 0, 126, 0.015) 1px, transparent 1px, transparent 10px),
        linear-gradient(135deg, #05000B 0%, #0d0818 50%, #05000B 100%) !important;
    color: #F8F9FA;
}

/* Header Banner - STEM Racing Panamá Official Style */
.sr-header-container {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(18, 14, 28, 0.88);
    background-image: repeating-linear-gradient(-60deg, rgba(255, 255, 255, 0.015) 0px, rgba(255, 255, 255, 0.015) 2px, transparent 2px, transparent 16px);
    border: 1px solid rgba(230, 0, 126, 0.35);
    border-radius: 16px;
    padding: 18px 28px;
    margin-bottom: 24px;
    box-shadow: 0 8px 32px rgba(5, 0, 11, 0.6);
    backdrop-filter: blur(12px);
    position: relative;
    overflow: hidden;
}

.sr-header-container::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, #E6007E 0%, #ED6D05 50%, #FCBC00 100%);
}

.sr-header-left {
    display: flex;
    align-items: center;
    gap: 22px;
}

.sr-header-title {
    font-size: 26px;
    font-weight: 900 !important;
    font-style: italic !important;
    letter-spacing: 0.8px;
    background: linear-gradient(90deg, #FFFFFF 0%, #FFFFFF 30%, #ED6D05 70%, #E6007E 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-transform: uppercase;
    margin: 0;
}

.sr-header-tag {
    font-size: 16px;
    font-weight: 800;
    font-style: italic;
    color: #FCBC00;
    letter-spacing: 1.2px;
    background: rgba(252, 188, 0, 0.12);
    padding: 8px 18px;
    border-radius: 30px;
    border: 1px solid rgba(252, 188, 0, 0.45);
    box-shadow: 0 0 16px rgba(252, 188, 0, 0.15);
}

/* Tab Styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: rgba(18, 14, 28, 0.85);
    padding: 8px 12px;
    border-radius: 14px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    overflow-x: auto;
}
.stTabs [data-baseweb="tab"] {
    height: 44px;
    white-space: nowrap;
    background-color: transparent;
    border-radius: 8px;
    color: #A09EB8;
    font-weight: 700;
    font-size: 13px;
    padding: 0 16px;
    border: none;
    transition: all 0.2s ease-in-out;
}
.stTabs [data-baseweb="tab"]:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #FFFFFF;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(90deg, rgba(230, 0, 126, 0.45) 0%, rgba(237, 109, 5, 0.45) 100%) !important;
    border: 1px solid #ED6D05 !important;
    color: #FFFFFF !important;
    font-style: italic !important;
    font-weight: 800 !important;
    box-shadow: 0 4px 18px rgba(230, 0, 126, 0.35);
}

/* Broadcast Leaderboard Row (Slide 1 style) */
.sr-broadcast-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: rgba(27, 18, 54, 0.75);
    border-left: 5px solid #FF8A00;
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    border-right: 1px solid rgba(255, 255, 255, 0.06);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    transition: transform 0.15s ease, background 0.15s ease;
}
.sr-broadcast-row:hover {
    transform: translateX(4px);
    background: rgba(42, 28, 80, 0.85);
    border-left-color: #FF2A85;
}
.sr-rank-badge {
    font-size: 18px;
    font-weight: 900;
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.08);
    color: #FFFFFF;
}
.sr-rank-1 {
    font-size: 18px;
    font-weight: 900;
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: linear-gradient(135deg, #FFD700 0%, #FFA500 100%);
    color: #120A00;
    box-shadow: 0 0 12px rgba(255, 215, 0, 0.6);
}
.sr-rank-2 {
    font-size: 18px;
    font-weight: 900;
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: linear-gradient(135deg, #E0E0E0 0%, #9E9E9E 100%);
    color: #1A1A1A;
    box-shadow: 0 0 10px rgba(224, 224, 224, 0.5);
}
.sr-rank-3 {
    font-size: 18px;
    font-weight: 900;
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: linear-gradient(135deg, #E69550 0%, #B86520 100%);
    color: #1A0D00;
    box-shadow: 0 0 10px rgba(205, 127, 50, 0.5);
}

.sr-team-name {
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: #FFFFFF;
}
.sr-time-val {
    font-size: 19px;
    font-weight: 900;
    color: #009FE3;
    letter-spacing: 0.5px;
    font-variant-numeric: tabular-nums;
}
.sr-delta-val {
    font-size: 14px;
    font-weight: 700;
    color: #ED6D05;
    font-variant-numeric: tabular-nums;
}
.sr-points-badge {
    font-size: 15px;
    font-weight: 800;
    padding: 5px 12px;
    border-radius: 20px;
    background: rgba(230, 0, 126, 0.25);
    color: #FF5DA2;
    border: 1px solid rgba(230, 0, 126, 0.5);
}

/* Podium 3D Pedestals - Official Colors */
.sr-podium-container {
    display: flex;
    justify-content: center;
    align-items: flex-end;
    gap: 20px;
    margin: 32px auto;
    padding: 20px 0;
    max-width: 850px;
    width: 100%;
}
.sr-podium-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    flex: 1;
    min-width: 180px;
    max-width: 260px;
}
.sr-pedestal {
    width: 100%;
    border-radius: 16px 16px 0 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 20px 14px;
    font-weight: 900;
    box-shadow: 0 12px 32px rgba(0,0,0,0.5);
    border-top: 3px solid rgba(255, 255, 255, 0.4);
    box-sizing: border-box;
    text-align: center;
}
.sr-pedestal-1 {
    height: 240px;
    background: linear-gradient(180deg, #FCBC00 0%, #B87C00 100%);
    color: #150C00;
    box-shadow: 0 0 35px rgba(252, 188, 0, 0.55);
    border-top: 3px solid #FFF275;
}
.sr-pedestal-2 {
    height: 180px;
    background: linear-gradient(180deg, #E6E8EB 0%, #767B85 100%);
    color: #0E1217;
    box-shadow: 0 0 25px rgba(220, 225, 235, 0.4);
    border-top: 3px solid #FFFFFF;
}
.sr-pedestal-3 {
    height: 140px;
    background: linear-gradient(180deg, #ED6D05 0%, #994400 100%);
    color: #190B00;
    box-shadow: 0 0 25px rgba(237, 109, 5, 0.45);
    border-top: 3px solid #FFBE85;
}

/* Presentation Table (PPTX Style) */
.sr-pptx-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(18, 14, 28, 0.88);
    margin: 16px 0;
}
.sr-pptx-table th {
    background: linear-gradient(90deg, #1F1640 0%, #120B24 100%);
    color: #FFFFFF;
    font-weight: 800;
    font-style: italic;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    padding: 14px 16px;
    border-bottom: 2px solid #E6007E;
    text-align: left;
}
.sr-pptx-table td {
    padding: 13px 16px;
    font-size: 15px;
    font-weight: 600;
    color: #E6E4F0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.sr-pptx-table tr:last-child td {
    border-bottom: none;
}
.sr-pptx-table tr:hover td {
    background: rgba(230, 0, 126, 0.06);
    color: #FFFFFF;
}

/* Winner Badges */
.sr-badge-win {
    background: #008A3F;
    color: #FFFFFF;
    font-weight: 800;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 6px;
    text-transform: uppercase;
}

/* Metrics box */
.sr-metric-box {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px;
    text-align: center;
}
.sr-metric-label {
    font-size: 12px;
    font-weight: 700;
    color: #A5A2BD;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.sr-metric-value {
    font-size: 24px;
    font-weight: 900;
    color: #FFFFFF;
    margin-top: 4px;
}
.sr-dnf-badge {
    background: rgba(230, 0, 126, 0.22);
    color: #E6007E;
    border: 1px solid rgba(230, 0, 126, 0.7);
    font-weight: 800;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: inline-block;
}

.sr-pending-badge {
    color: #6C6885;
    font-size: 12px;
    font-weight: 600;
    font-style: italic;
}

.sr-fs-badge {
    background: rgba(237, 109, 5, 0.22);
    color: #ED6D05;
    border: 1px solid rgba(237, 109, 5, 0.7);
    font-weight: 800;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: inline-block;
}

/* Greyed out disabled inputs for DNF and False Start */
input:disabled, .stTextInput input:disabled, div[data-baseweb="input"] input:disabled {
    background-color: rgba(28, 22, 44, 0.90) !important;
    color: #A09EB8 !important;
    -webkit-text-fill-color: #A09EB8 !important;
    border: 1px solid rgba(255, 255, 255, 0.16) !important;
    font-weight: 800 !important;
    letter-spacing: 1px !important;
    cursor: not-allowed !important;
}

/* Leader Highlight Banner */
.sr-leader-banner {
    background: linear-gradient(90deg, rgba(0, 159, 227, 0.18) 0%, rgba(237, 109, 5, 0.18) 50%, rgba(230, 0, 126, 0.18) 100%);
    border: 2px solid #009FE3;
    border-radius: 16px;
    padding: 20px 30px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 8px 32px rgba(0, 159, 227, 0.2);
}

/* Slide Ceremony Animations */
@keyframes srFadeSlideUp {
    0% {
        opacity: 0;
        transform: translateY(32px) scale(0.97);
    }
    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

@keyframes srRisePedestal {
    0% {
        opacity: 0;
        transform: translateY(70px) scaleY(0.15);
        transform-origin: bottom;
    }
    75% {
        opacity: 1;
        transform: translateY(-5px) scaleY(1.03);
        transform-origin: bottom;
    }
    100% {
        opacity: 1;
        transform: translateY(0) scaleY(1);
        transform-origin: bottom;
    }
}

.sr-anim-1 {
    opacity: 0;
    animation: srFadeSlideUp 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.08s forwards;
}
.sr-anim-2 {
    opacity: 0;
    animation: srFadeSlideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) 0.45s forwards;
}
.sr-anim-3 {
    opacity: 0;
    animation: srFadeSlideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) 0.9s forwards;
}
.sr-anim-4 {
    opacity: 0;
    animation: srFadeSlideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) 1.35s forwards;
}

/* Slide Ceremony Reveal Order: Title -> Category Scores First -> Winner Climax Last */
.sr-anim-title {
    opacity: 0;
    animation: srFadeSlideUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) 0.1s forwards;
}
.sr-anim-categories {
    opacity: 0;
    animation: srFadeSlideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) 0.35s forwards;
}

@keyframes srWinnerPopReveal {
    0% {
        opacity: 0;
        transform: scale(0.86) translateY(24px);
        filter: blur(4px);
    }
    65% {
        opacity: 1;
        transform: scale(1.03) translateY(-3px);
        filter: blur(0);
    }
    100% {
        opacity: 1;
        transform: scale(1) translateY(0);
        filter: blur(0);
    }
}

.sr-anim-winner {
    opacity: 0;
    animation: srWinnerPopReveal 0.9s cubic-bezier(0.22, 1, 0.36, 1) 1.85s forwards;
}

/* Sequential Podium Reveal: 3ro -> 2do -> 1ro -> Tabla */
.sr-podium-anim-3 {
    opacity: 0;
    animation: srRisePedestal 0.8s cubic-bezier(0.22, 1, 0.36, 1) 0.15s forwards;
}
.sr-podium-anim-2 {
    opacity: 0;
    animation: srRisePedestal 0.8s cubic-bezier(0.22, 1, 0.36, 1) 0.95s forwards;
}
.sr-podium-anim-1 {
    opacity: 0;
    animation: srRisePedestal 0.9s cubic-bezier(0.22, 1, 0.36, 1) 1.80s forwards;
}
.sr-podium-anim-table {
    opacity: 0;
    animation: srFadeSlideUp 0.8s cubic-bezier(0.22, 1, 0.36, 1) 2.65s forwards;
}

/* ==========================================================================
   OFFICIAL STEM RACING - JUDGING BREAKDOWN SCORECARD STYLES
   ========================================================================== */
.sr-judging-panel {
    background: rgba(18, 14, 28, 0.92);
    border: 1px solid rgba(230, 0, 126, 0.35);
    border-radius: 16px;
    padding: 22px 26px;
    margin-bottom: 24px;
    box-shadow: 0 10px 36px rgba(5, 0, 11, 0.7);
    backdrop-filter: blur(14px);
    position: relative;
    overflow: hidden;
}
.sr-judging-panel::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: linear-gradient(90deg, #E6007E 0%, #ED6D05 35%, #FCBC00 70%, #009FE3 100%);
}
.sr-judging-header-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    background: rgba(230, 0, 126, 0.15);
    border: 1px solid rgba(230, 0, 126, 0.45);
    color: #FF6BAC;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.sr-judging-title {
    font-size: 26px;
    font-weight: 900;
    font-style: italic;
    color: #FFFFFF;
    margin: 0 0 6px 0;
    letter-spacing: 0.5px;
}
.sr-judging-subtitle {
    font-size: 13px;
    color: #A0A0B5;
    margin: 0 0 18px 0;
}
.sr-judging-cat-box {
    background: rgba(25, 20, 38, 0.82);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-left: 5px solid #00ADB5;
    padding: 16px 20px;
    margin-bottom: 18px;
    transition: all 0.25s ease;
}
.sr-judging-cat-box:hover {
    border-color: rgba(255, 255, 255, 0.20);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.40);
}
.sr-judging-cat-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.sr-judging-cat-name {
    font-size: 16px;
    font-weight: 800;
    font-style: italic;
    color: #FFFFFF;
    letter-spacing: 0.3px;
}
.sr-judging-cat-subtotal {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 4px 12px;
    border-radius: 12px;
    font-weight: 800;
    font-size: 14px;
    letter-spacing: 0.5px;
}
.sr-subcat-label {
    font-size: 13px;
    font-weight: 600;
    color: #E2E2EA;
}
.sr-subcat-note {
    font-size: 11px;
    color: #9292A6;
    margin-left: 4px;
}
.sr-subcat-cap {
    font-size: 11px;
    font-weight: 700;
    color: #FCBC00;
    background: rgba(252, 188, 0, 0.12);
    padding: 2px 7px;
    border-radius: 6px;
    border: 1px solid rgba(252, 188, 0, 0.30);
    display: inline-block;
}
.sr-racing-sync-card {
    background: linear-gradient(135deg, rgba(0, 159, 227, 0.12) 0%, rgba(49, 39, 131, 0.18) 100%);
    border: 1px solid rgba(0, 159, 227, 0.45);
    border-left: 5px solid #009FE3;
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 18px;
}
.sr-grand-total-banner {
    background: linear-gradient(135deg, rgba(230, 0, 126, 0.22) 0%, rgba(237, 109, 5, 0.20) 50%, rgba(252, 188, 0, 0.15) 100%);
    border: 2px solid rgba(230, 0, 126, 0.65);
    border-radius: 16px;
    padding: 20px 24px;
    margin: 20px 0;
    box-shadow: 0 12px 38px rgba(230, 0, 126, 0.25);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
}
.sr-grand-total-score {
    font-size: 34px;
    font-weight: 900;
    font-style: italic;
    color: #FCBC00;
    text-shadow: 0 0 18px rgba(252, 188, 0, 0.60);
    letter-spacing: 0.5px;
}
.sr-matrix-table-wrap {
    background: rgba(18, 14, 28, 0.90);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 14px;
    padding: 18px;
    margin-top: 24px;
    overflow-x: auto;
}
</style>"""
    return css


def render_app_header(logo_b64: str = "") -> str:
    """Renders the top branding banner without any leading indentation."""
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height: 52px; width: auto;" alt="STEM Racing Panamá"/>' if logo_b64 else '<span style="font-size: 26px; font-weight: 900; font-style: italic; color: #ED6D05;">🏁 STEM RACING PANAMÁ</span>'
    html = f"""<div class="sr-header-container">
    <div class="sr-header-left">
        {logo_html}
        <div>
            <h1 class="sr-header-title">Visualizador de Resultados</h1>
        </div>
    </div>
    <div class="sr-header-tag">@STEMRacingPa</div>
</div>"""
    return html


TEAM_LOGO_FILES = {
    "BoscoTech": "logo_boscotech.png",
    "JAF Racing Team": "logo_jaf_racing_team.png",
    "Excalibur": "logo_excalibur.png",
    "Rayo Rabin": "logo_rayo_rabin.png",
    "Hayai Aerodynamics": "logo_hayai_aerodynamics.png",
    "Dim3nsion": "logo_dim3nsion.png",
    "Raiders": "logo_raiders.png",
    "Cybercolts Racing": "logo_cybercolts_racing.png",
    "PNTHR": "logo_pnthr.png",
}


def load_team_logos_b64(assets_dir: str) -> dict:
    """Load base64-encoded PNG logos (downscaled to 132x90 max) for all teams in assets."""
    logos = {}
    for team_name, filename in TEAM_LOGO_FILES.items():
        path = os.path.join(assets_dir, filename)
        b64 = get_base64_encoded_image(path, max_size=(132, 90))
        if b64:
            logos[team_name] = b64
    return logos


def get_team_logo_html(team_name: str, logos_b64: dict, height: int = 30, fallback_emoji: str = "🏎️") -> str:
    """Return an inline HTML badge with fixed uniform dimensions (220:150 aspect ratio) for homogeneous display."""
    width = int(round(height * (220.0 / 150.0)))
    b64 = logos_b64.get(str(team_name).strip(), "") if logos_b64 else ""
    if b64:
        return (
            f'<img src="data:image/png;base64,{b64}" alt="{team_name}" '
            f'style="width:{width}px; height:{height}px; object-fit:cover; '
            f'border-radius:6px; border:1px solid rgba(255,255,255,0.22); '
            f'vertical-align:middle; box-shadow:0 2px 8px rgba(0,0,0,0.45); flex-shrink:0; display:inline-block;" />'
        )
    return (
        f'<span style="width:{width}px; height:{height}px; border-radius:6px; '
        f'background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.22); '
        f'display:inline-flex; align-items:center; justify-content:center; '
        f'font-size:{max(13, int(height*0.58))}px; vertical-align:middle; line-height:1; '
        f'box-shadow:0 2px 8px rgba(0,0,0,0.45); flex-shrink:0;">{fallback_emoji}</span>'
    )


def render_team_with_logo(team_name: str, logos_b64: dict, height: int = 30, gap: int = 10) -> str:
    """Return an inline flex container with the team's uniform logo badge and name."""
    icon = get_team_logo_html(team_name, logos_b64, height=height)
    return f'<span style="display:inline-flex; align-items:center; gap:{gap}px; vertical-align:middle;">{icon}<span>{team_name}</span></span>'
