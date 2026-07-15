"""
api_server.py — Cloud signal API for Regime Desk.

Computes ticker signals on demand using yfinance (no local database required).
Deploy to Render, Railway, or any Python host.

Endpoints:
  GET /api/ping              — health check
  GET /api/ticker?t=TICKER   — compute signal for TICKER
"""
import math
import os
import re
import threading
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request

app = Flask(__name__)

SIMILAR_DAY_COUNT = 30
EXCLUDE_RECENT_DAYS = 30
MIN_OBSERVATIONS = 5
HORIZONS = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}

_state = {
    "spy_df": None,
    "analog_dates": None,
    "ticker_cache": {},
    "last_refresh": None,
    "lock": threading.Lock(),
}

_SECTOR_MAP = {
    'A': 'Healthcare', 'AA': 'Materials', 'AAAU': 'Materials', 'AAL': 'Industrials',
    'AAOI': 'Technology', 'AAON': 'Industrials', 'AAP': 'Consumer Discretionary', 'AAPL': 'Technology',
    'ABBV': 'Healthcare', 'ABNB': 'Consumer Discretionary', 'ABT': 'Healthcare', 'ACGL': 'Financials',
    'ACHR': 'Defense', 'ACI': 'Consumer Staples', 'ACLX': 'Biotech', 'ACM': 'Industrials',
    'ACMR': 'Semiconductors', 'ACN': 'Technology', 'ADBE': 'Technology', 'ADC': 'Real Estate',
    'ADI': 'Semiconductors', 'ADM': 'Consumer Staples', 'ADP': 'Technology', 'ADSK': 'Technology',
    'AEE': 'Utilities', 'AEIS': 'Industrials', 'AEM': 'Materials', 'AEO': 'Consumer Discretionary',
    'AEP': 'Utilities', 'AER': 'Industrials', 'AES': 'Utilities', 'AEVA': 'Technology',
    'AFG': 'Financials', 'AFL': 'Financials', 'AFRM': 'Financials', 'AG': 'Materials',
    'AGCO': 'Industrials', 'AGI': 'Materials', 'AGNC': 'Real Estate', 'AGQ': 'Materials',
    'AGX': 'Industrials', 'AHR': 'Real Estate', 'AI': 'Technology', 'AIG': 'Financials',
    'AIR': 'Defense', 'AIT': 'Industrials', 'AIZ': 'Financials', 'AJG': 'Financials',
    'AKAM': 'Technology', 'AL': 'Industrials', 'ALAB': 'Semiconductors', 'ALB': 'Materials',
    'ALC': 'Healthcare', 'ALGM': 'Semiconductors', 'ALGN': 'Healthcare', 'ALHC': 'Healthcare',
    'ALK': 'Industrials', 'ALKS': 'Healthcare', 'ALL': 'Financials', 'ALLE': 'Industrials',
    'ALLY': 'Financials', 'ALMS': 'Biotech', 'ALNY': 'Biotech', 'ALSN': 'Consumer Discretionary',
    'ALV': 'Consumer Discretionary', 'AMAT': 'Semiconductors', 'AMBA': 'Semiconductors', 'AMC': 'Communication Services',
    'AMCR': 'Consumer Discretionary', 'AMD': 'Semiconductors', 'AME': 'Industrials', 'AMG': 'Financials',
    'AMGN': 'Healthcare', 'AMH': 'Real Estate', 'AMKR': 'Semiconductors', 'AMP': 'Financials',
    'AMPX': 'Industrials', 'AMR': 'Materials', 'AMRZ': 'Materials', 'AMT': 'Real Estate',
    'AMTM': 'Industrials', 'AMZN': 'Consumer Discretionary', 'AN': 'Consumer Discretionary', 'ANET': 'Technology',
    'ANF': 'Consumer Discretionary', 'AON': 'Financials', 'AOS': 'Industrials', 'APA': 'Energy',
    'APD': 'Materials', 'APG': 'Industrials', 'APGE': 'Biotech', 'APH': 'Technology',
    'APLD': 'Technology', 'APLS': 'Biotech', 'APO': 'Financials', 'APP': 'Communication Services',
    'APPF': 'Technology', 'APTV': 'Consumer Discretionary', 'AR': 'Energy', 'ARCC': 'Financials',
    'ARE': 'Real Estate', 'ARES': 'Financials', 'ARKB': 'Crypto', 'ARKX': 'Defense', 'ARMK': 'Industrials',
    'ARR': 'Real Estate', 'ARRY': 'Energy Transition', 'ARWR': 'Biotech', 'AS': 'Consumer Discretionary',
    'ASB': 'Financials', 'ASM': 'Materials', 'ASML': 'Semiconductors', 'ASO': 'Consumer Discretionary',
    'ASST': 'Financials', 'ASTS': 'Technology', 'ATEC': 'Healthcare', 'ATI': 'Industrials',
    'ATO': 'Energy', 'ATRO': 'Defense', 'AU': 'Materials', 'AUR': 'Technology',
    'AVAV': 'Defense', 'AVGO': 'Semiconductors', 'AVTR': 'Healthcare', 'AVY': 'Consumer Discretionary',
    'AWI': 'Industrials', 'AWK': 'Utilities', 'AXON': 'Defense', 'AXP': 'Financials',
    'AXS': 'Financials', 'AXSM': 'Biotech', 'AXTA': 'Materials', 'AXTI': 'Semiconductors',
    'AYI': 'Industrials', 'AZO': 'Consumer Discretionary', 'B': 'Materials', 'BA': 'Defense',
    'BAC': 'Financials', 'BAH': 'Industrials', 'BALL': 'Consumer Discretionary', 'BAM': 'Financials',
    'BAP': 'Financials', 'BAX': 'Healthcare', 'BBAI': 'Technology', 'BBIO': 'Biotech',
    'BBWI': 'Consumer Discretionary', 'BBY': 'Consumer Discretionary', 'BC': 'Consumer Discretionary', 'BCE': 'Communication Services',
    'BCS': 'Financials', 'BDX': 'Healthcare', 'BE': 'Industrials', 'BEAM': 'Biotech',
    'BEN': 'Financials', 'BF-B': 'Consumer Staples', 'BF.B': 'Consumer Staples', 'BFAM': 'Consumer Discretionary',
    'BFH': 'Financials', 'BG': 'Consumer Staples', 'BHF': 'Financials', 'BIIB': 'Healthcare',
    'BILL': 'Technology', 'BIO': 'Healthcare', 'BIRK': 'Consumer Discretionary', 'BITB': 'Crypto',
    'BITF': 'Financials', 'BITO': 'Crypto', 'BITU': 'Crypto', 'BITX': 'Crypto',
    'BJ': 'Consumer Staples', 'BK': 'Financials', 'BKH': 'Energy', 'BKNG': 'Consumer Discretionary',
    'BKR': 'Energy', 'BLD': 'Industrials', 'BLDR': 'Industrials', 'BLK': 'Financials',
    'BLSH': 'Technology', 'BMNR': 'Financials', 'BMO': 'Financials', 'BMRN': 'Biotech',
    'BMY': 'Healthcare', 'BN': 'Financials', 'BNAI': 'Technology', 'BNS': 'Financials',
    'BOIL': 'Energy', 'BOOT': 'Consumer Discretionary', 'BOX': 'Technology', 'BP': 'Energy',
    'BPOP': 'Financials', 'BR': 'Technology', 'BRBR': 'Consumer Staples', 'BRK-A': 'Financials',
    'BRK-B': 'Financials', 'BRKR': 'Healthcare', 'BRO': 'Financials', 'BROS': 'Consumer Discretionary',
    'BRX': 'Real Estate', 'BRZE': 'Technology', 'BSX': 'Healthcare', 'BSY': 'Technology',
    'BTBT': 'Financials', 'BTC': 'Crypto', 'BTCZ': 'Crypto', 'BTDR': 'Technology',
    'BTE': 'Energy', 'BTG': 'Materials', 'BTGO': 'Financials', 'BTI': 'Consumer Staples',
    'BTU': 'Energy', 'BUD': 'Consumer Staples', 'BULL': 'Technology', 'BURL': 'Consumer Discretionary',
    'BVN': 'Materials', 'BWA': 'Consumer Discretionary', 'BWXT': 'Defense', 'BX': 'Financials',
    'BXP': 'Real Estate', 'BYD': 'Consumer Discretionary', 'BYND': 'Consumer Staples', 'BZ': 'Communication Services',
    'C': 'Financials', 'CACC': 'Financials', 'CACI': 'Technology', 'CAG': 'Consumer Staples',
    'CAH': 'Healthcare', 'CAI': 'Biotech', 'CAKE': 'Consumer Discretionary', 'CALM': 'Consumer Staples',
    'CAMT': 'Semiconductors', 'CAR': 'Industrials', 'CARR': 'Industrials', 'CART': 'Consumer Discretionary',
    'CASY': 'Consumer Discretionary', 'CAT': 'Industrials', 'CAVA': 'Consumer Discretionary', 'CB': 'Financials',
    'CBOE': 'Financials', 'CBRE': 'Real Estate', 'CBRL': 'Consumer Discretionary', 'CBSH': 'Financials',
    'CCC': 'Technology', 'CCEP': 'Consumer Staples', 'CCI': 'Real Estate', 'CCJ': 'Energy',
    'CCK': 'Consumer Discretionary', 'CCL': 'Consumer Discretionary', 'CDE': 'Materials', 'CDNS': 'Technology',
    'CDW': 'Technology', 'CE': 'Materials', 'CEF': 'Materials', 'CEG': 'Utilities',
    'CELC': 'Biotech', 'CELH': 'Consumer Staples', 'CENX': 'Materials', 'CF': 'Materials',
    'CFG': 'Financials', 'CFLT': 'Technology', 'CFR': 'Financials', 'CG': 'Financials',
    'CGNX': 'Technology', 'CGON': 'Biotech', 'CHD': 'Consumer Staples', 'CHDN': 'Consumer Discretionary',
    'CHE': 'Healthcare', 'CHH': 'Consumer Discretionary', 'CHKP': 'Technology', 'CHRD': 'Energy',
    'CHRW': 'Logistics', 'CHTR': 'Communication Services', 'CHWY': 'Consumer Discretionary', 'CHYM': 'Technology',
    'CI': 'Healthcare', 'CIEN': 'Technology', 'CIFR': 'Materials', 'CINF': 'Financials',
    'CL': 'Consumer Staples', 'CLF': 'Materials', 'CLH': 'Industrials', 'CLS': 'Technology',
    'CLSK': 'Financials', 'CLX': 'Consumer Staples', 'CM': 'Financials', 'CMC': 'Materials',
    'CMCSA': 'Communication Services', 'CME': 'Financials', 'CMG': 'Semiconductors', 'CMI': 'Industrials',
    'CMS': 'Utilities', 'CNC': 'Healthcare', 'CNH': 'Industrials', 'CNI': 'Industrials',
    'CNK': 'Communication Services', 'CNM': 'Industrials', 'CNP': 'Utilities', 'CNQ': 'Energy',
    'CNR': 'Energy', 'CNX': 'Energy', 'COF': 'Financials', 'COGT': 'Biotech',
    'COHR': 'Technology', 'COIN': 'Financials', 'COKE': 'Consumer Staples', 'COLB': 'Financials',
    'COLD': 'Real Estate', 'COMP': 'Real Estate', 'COO': 'Healthcare', 'COP': 'Energy',
    'COPX': 'Materials', 'COR': 'Healthcare', 'CORT': 'Biotech', 'CORZ': 'Technology',
    'COST': 'Consumer Staples', 'CP': 'Industrials', 'CPAY': 'Technology', 'CPB': 'Consumer Staples',
    'CPER': 'Materials', 'CPNG': 'Consumer Discretionary', 'CPRI': 'Consumer Discretionary', 'CPRT': 'Industrials',
    'CPT': 'Real Estate', 'CR': 'Industrials', 'CRBG': 'Financials', 'CRCL': 'Financials',
    'CRDO': 'Semiconductors', 'CRH': 'Materials', 'CRK': 'Energy', 'CRL': 'Healthcare',
    'CRM': 'Technology', 'CRML': 'Materials', 'CRNX': 'Biotech', 'CROX': 'Consumer Discretionary',
    'CRS': 'Industrials', 'CRSP': 'Biotech', 'CRUS': 'Semiconductors', 'CRVS': 'Biotech',
    'CRWD': 'Technology', 'CRWV': 'Technology', 'CSCO': 'Technology', 'CSGP': 'Real Estate',
    'CSIQ': 'Energy Transition', 'CSL': 'Industrials', 'CSX': 'Industrials', 'CTAS': 'Industrials',
    'CTRA': 'Energy', 'CTRE': 'Real Estate', 'CTSH': 'Technology', 'CTVA': 'Materials',
    'CUBE': 'Real Estate', 'CUK': 'Consumer Discretionary', 'CVCO': 'Consumer Discretionary', 'CVE': 'Energy',
    'CVLT': 'Technology', 'CVNA': 'Consumer Discretionary', 'CVS': 'Healthcare', 'CVX': 'Energy',
    'CW': 'Industrials', 'CWAN': 'Technology', 'CWST': 'Industrials', 'CX': 'Materials',
    'CYTK': 'Biotech', 'CZR': 'Consumer Discretionary', 'D': 'Utilities', 'DAL': 'Industrials',
    'DAR': 'Consumer Staples', 'DASH': 'Consumer Discretionary', 'DAVE': 'Technology', 'DB': 'Financials',
    'DBRG': 'Financials', 'DBX': 'Technology', 'DCI': 'Industrials', 'DD': 'Materials',
    'DDOG': 'Technology', 'DDS': 'Consumer Discretionary', 'DE': 'Industrials', 'DECK': 'Consumer Discretionary',
    'DELL': 'Technology', 'DEO': 'Consumer Staples', 'DG': 'Consumer Staples', 'DGX': 'Healthcare',
    'DHI': 'Consumer Discretionary', 'DHR': 'Healthcare', 'DINO': 'Energy', 'DIS': 'Communication Services',
    'DJCO': 'Technology', 'DJT': 'Communication Services', 'DKNG': 'Consumer Discretionary', 'DKS': 'Consumer Discretionary',
    'DLR': 'Real Estate', 'DLTR': 'Consumer Staples', 'DNN': 'Energy', 'DOC': 'Real Estate',
    'DOCN': 'Technology', 'DOCS': 'Healthcare', 'DOCU': 'Technology', 'DOV': 'Industrials',
    'DOW': 'Materials', 'DOX': 'Technology', 'DPZ': 'Consumer Discretionary', 'DRAM': 'Semiconductors',
    'DRI': 'Consumer Discretionary', 'DRIP': 'Energy', 'DT': 'Technology', 'DTCR': 'Real Estate',
    'DTE': 'Utilities', 'DTM': 'Energy',
    'DUK': 'Utilities', 'DUOL': 'Technology', 'DUST': 'Materials', 'DVA': 'Healthcare',
    'DVLT': 'Technology', 'DVN': 'Energy', 'DX': 'Real Estate', 'DXCM': 'Healthcare',
    'DY': 'Industrials', 'EA': 'Communication Services', 'EAT': 'Consumer Discretionary', 'EBAY': 'Consumer Discretionary',
    'ECG': 'Industrials', 'ECL': 'Materials', 'ED': 'Utilities', 'EFX': 'Industrials',
    'EG': 'Financials', 'EGO': 'Materials', 'EGP': 'Real Estate', 'EHC': 'Healthcare',
    'EIX': 'Utilities', 'EKSO': 'Healthcare', 'EL': 'Consumer Staples', 'ELAN': 'Healthcare',
    'ELF': 'Consumer Staples', 'ELS': 'Real Estate', 'ELV': 'Healthcare', 'EMBJ': 'Industrials',
    'EME': 'Industrials', 'EMN': 'Materials', 'EMR': 'Industrials', 'ENB': 'Energy',
    'ENPH': 'Technology', 'ENS': 'Industrials', 'ENSG': 'Healthcare', 'ENTG': 'Technology',
    'EOG': 'Energy', 'EOSE': 'Industrials', 'EPAM': 'Technology', 'EPD': 'Energy',
    'EPRT': 'Real Estate', 'EQH': 'Financials', 'EQIX': 'Real Estate', 'EQNR': 'Energy',
    'EQPT': 'Industrials', 'EQR': 'Real Estate', 'EQT': 'Energy', 'EQX': 'Materials',
    'ERAS': 'Healthcare', 'ERO': 'Materials', 'ES': 'Utilities', 'ESLT': 'Industrials',
    'ESS': 'Real Estate', 'ESTC': 'Technology', 'ETN': 'Industrials', 'ETR': 'Utilities',
    'ETSY': 'Consumer Discretionary', 'EVR': 'Financials', 'EVRG': 'Utilities', 'EVTV': 'Consumer Discretionary',
    'EW': 'Healthcare', 'EWBC': 'Financials', 'EXAS': 'Healthcare', 'EXC': 'Utilities',
    'EXE': 'Energy', 'EXEL': 'Healthcare', 'EXK': 'Materials', 'EXP': 'Materials',
    'EXPD': 'Industrials', 'EXPE': 'Consumer Discretionary', 'EXR': 'Real Estate', 'F': 'Consumer Discretionary',
    'FAF': 'Financials', 'FANG': 'Energy', 'FAST': 'Industrials', 'FBIN': 'Industrials',
    'FBT': 'Biotech', 'FBTC': 'Crypto', 'FCNCA': 'Financials', 'FCX': 'Materials',
    'FDS': 'Financials', 'FDX': 'Industrials', 'FE': 'Utilities', 'FER': 'Industrials',
    'FERG': 'Industrials', 'FFIV': 'Technology', 'FHN': 'Financials', 'FICO': 'Technology',
    'FIG': 'Technology', 'FIGR': 'Financials', 'FIS': 'Technology', 'FITB': 'Financials',
    'FIVE': 'Consumer Discretionary', 'FIX': 'Industrials', 'FLEX': 'Technology', 'FLG': 'Financials',
    'FLNC': 'Utilities', 'FLR': 'Industrials', 'FLS': 'Industrials', 'FLUT': 'Consumer Discretionary',
    'FLY': 'Defense', 'FMC': 'Materials', 'FN': 'Technology', 'FNB': 'Financials',
    'FND': 'Consumer Discretionary', 'FNF': 'Financials', 'FNV': 'Materials', 'FOLD': 'Biotech',
    'FORM': 'Technology', 'FOUR': 'Technology', 'FOX': 'Communication Services', 'FOXA': 'Communication Services',
    'FR': 'Real Estate', 'FRMI': 'Real Estate', 'FRO': 'Energy', 'FROG': 'Technology',
    'FRPT': 'Consumer Staples', 'FRT': 'Real Estate', 'FSLR': 'Energy Transition', 'FSM': 'Materials',
    'FTAI': 'Industrials', 'FTI': 'Energy', 'FTNT': 'Technology', 'FTS': 'Utilities',
    'FTV': 'Technology', 'FWONK': 'Communication Services', 'G': 'Technology', 'GAP': 'Consumer Discretionary',
    'GBIL': 'Materials', 'GBTC': 'Crypto', 'GD': 'Industrials', 'GDDY': 'Technology',
    'GDX': 'Materials', 'GDXJ': 'Materials', 'GDXU': 'Materials', 'GE': 'Defense',
    'GEHC': 'Healthcare', 'GEN': 'Technology', 'GEV': 'Industrials', 'GFL': 'Industrials',
    'GFS': 'Technology', 'GGG': 'Industrials', 'GH': 'Healthcare', 'GIL': 'Consumer Discretionary',
    'GILD': 'Healthcare', 'GIS': 'Consumer Staples', 'GKOS': 'Healthcare', 'GL': 'Financials',
    'GLD': 'Materials', 'GLDM': 'Materials', 'GLL': 'Materials', 'GLOB': 'Technology',
    'GLPI': 'Real Estate', 'GLUE': 'Biotech', 'GLW': 'Technology', 'GLXY': 'Financials',
    'GM': 'Consumer Discretionary', 'GME': 'Consumer Discretionary', 'GMED': 'Healthcare', 'GNRC': 'Industrials',
    'GNTX': 'Consumer Discretionary', 'GOOG': 'Communication Services', 'GOOGL': 'Communication Services', 'GPC': 'Consumer Discretionary',
    'GPI': 'Consumer Discretionary', 'GPIQ': 'Materials', 'GPK': 'Consumer Discretionary', 'GPN': 'Industrials',
    'GPOR': 'Energy', 'GRAB': 'Technology', 'GRAL': 'Healthcare', 'GRMN': 'Technology',
    'GS': 'Materials', 'GSLC': 'Materials', 'GTLB': 'Technology', 'GTLS': 'Industrials',
    'GVA': 'Industrials', 'GWRE': 'Technology', 'GWW': 'Industrials', 'GXO': 'Logistics',
    'H': 'Consumer Discretionary', 'HAE': 'Healthcare', 'HAL': 'Energy', 'HALO': 'Biotech',
    'HAS': 'Consumer Discretionary', 'HBAN': 'Financials', 'HBM': 'Materials', 'HCA': 'Healthcare',
    'HCC': 'Materials', 'HD': 'Consumer Discretionary', 'HDB': 'Financials', 'HE': 'Utilities',
    'HEI': 'Industrials', 'HEI-A': 'Industrials', 'HIG': 'Financials', 'HII': 'Industrials',
    'HIMS': 'Healthcare', 'HL': 'Materials', 'HLI': 'Financials', 'HLNE': 'Financials',
    'HLT': 'Consumer Discretionary', 'HMY': 'Materials', 'HOG': 'Consumer Discretionary', 'HOLX': 'Healthcare',
    'HON': 'Industrials', 'HOOD': 'Financials', 'HPE': 'Technology', 'HPQ': 'Technology',
    'HQY': 'Healthcare', 'HRB': 'Consumer Discretionary', 'HRI': 'Industrials', 'HRL': 'Consumer Staples',
    'HSBC': 'Financials', 'HSIC': 'Healthcare', 'HST': 'Real Estate', 'HSY': 'Consumer Staples',
    'HUBB': 'Industrials', 'HUBS': 'Technology', 'HUM': 'Healthcare', 'HUT': 'Financials',
    'HWC': 'Financials', 'HWM': 'Defense', 'HXL': 'Industrials', 'HYMC': 'Materials',
    'IAG': 'Materials', 'IAU': 'Materials', 'IAUM': 'Materials', 'IBB': 'Biotech',
    'IBIT': 'Crypto', 'IBKR': 'Financials', 'IBM': 'Technology', 'IBN': 'Financials',
    'IBP': 'Consumer Discretionary', 'ICE': 'Financials', 'ICLR': 'Healthcare', 'IDA': 'Utilities',
    'IDCC': 'Technology', 'IDXX': 'Healthcare', 'IESC': 'Industrials', 'IEX': 'Industrials',
    'IFF': 'Materials', 'ILMN': 'Healthcare', 'IMO': 'Energy', 'INBS': 'Healthcare',
    'INCY': 'Healthcare', 'INDV': 'Healthcare', 'INGR': 'Consumer Staples', 'INOD': 'Technology',
    'INSM': 'Healthcare', 'INSP': 'Healthcare', 'INTC': 'Technology', 'INTU': 'Technology',
    'INVH': 'Real Estate', 'IONQ': 'Technology', 'IONS': 'Biotech', 'IOT': 'Technology',
    'IP': 'Consumer Discretionary', 'IQV': 'Healthcare', 'IR': 'Industrials', 'IREN': 'Financials',
    'IRM': 'Real Estate', 'IRTC': 'Healthcare', 'ISRG': 'Healthcare', 'IT': 'Technology',
    'ITA': 'Defense', 'ITT': 'Industrials', 'ITW': 'Industrials', 'IVZ': 'Financials',
    'J': 'Industrials', 'JAZZ': 'Biotech', 'JBHT': 'Industrials', 'JBL': 'Technology',
    'JBLU': 'Industrials', 'JBS': 'Consumer Staples', 'JBTM': 'Industrials', 'JCI': 'Industrials',
    'JDST': 'Materials', 'JEF': 'Financials', 'JHG': 'Financials', 'JHX': 'Materials',
    'JKHY': 'Technology', 'JLL': 'Real Estate', 'JNJ': 'Healthcare', 'JNUG': 'Materials',
    'JOBY': 'Industrials', 'JPM': 'Financials', 'KBH': 'Consumer Discretionary', 'KBR': 'Industrials',
    'KDP': 'Consumer Staples', 'KEX': 'Industrials', 'KEY': 'Financials', 'KEYS': 'Technology',
    'KGC': 'Materials', 'KHC': 'Consumer Staples', 'KIM': 'Real Estate', 'KKR': 'Financials',
    'KLAC': 'Technology', 'KLAR': 'Technology', 'KMB': 'Consumer Staples', 'KMI': 'Energy',
    'KMX': 'Consumer Discretionary', 'KNSL': 'Financials', 'KNX': 'Logistics', 'KO': 'Consumer Staples',
    'KOLD': 'Energy', 'KR': 'Consumer Staples', 'KRC': 'Real Estate', 'KRMN': 'Industrials',
    'KRYS': 'Biotech', 'KSS': 'Consumer Discretionary', 'KTOS': 'Defense', 'KVUE': 'Consumer Staples',
    'KVYO': 'Technology', 'KYMR': 'Biotech', 'L': 'Financials', 'LABD': 'Biotech',
    'LABU': 'Biotech', 'LAC': 'Materials', 'LAD': 'Consumer Discretionary', 'LAMR': 'Real Estate',
    'LBRDK': 'Communication Services', 'LBRT': 'Energy', 'LCID': 'Consumer Discretionary', 'LDOS': 'Technology',
    'LEA': 'Consumer Discretionary', 'LECO': 'Industrials', 'LEN': 'Consumer Discretionary', 'LEU': 'Energy',
    'LFUS': 'Technology', 'LGN': 'Industrials', 'LH': 'Healthcare', 'LHX': 'Industrials',
    'LIF': 'Technology', 'LII': 'Industrials', 'LIN': 'Materials', 'LINE': 'Real Estate',
    'LITE': 'Technology', 'LKQ': 'Consumer Discretionary', 'LLY': 'Healthcare', 'LMND': 'Financials',
    'LMT': 'Industrials', 'LNC': 'Financials', 'LNG': 'Energy', 'LNT': 'Utilities',
    'LNTH': 'Healthcare', 'LOGI': 'Technology', 'LOW': 'Consumer Discretionary', 'LPLA': 'Financials',
    'LPX': 'Industrials', 'LQDA': 'Healthcare', 'LRCX': 'Technology', 'LRN': 'Consumer Staples',
    'LSCC': 'Semiconductors', 'LSTR': 'Industrials', 'LTH': 'Consumer Discretionary', 'LULU': 'Consumer Discretionary',
    'LUMN': 'Communication Services', 'LUNR': 'Industrials', 'LUV': 'Industrials', 'LVS': 'Energy',
    'LW': 'Consumer Staples', 'LYB': 'Materials', 'LYFT': 'Technology', 'LYV': 'Communication Services',
    'M': 'Consumer Discretionary', 'MA': 'Financials', 'MANH': 'Technology', 'MAR': 'Consumer Discretionary',
    'MARA': 'Financials', 'MAS': 'Industrials', 'MASI': 'Healthcare', 'MAT': 'Consumer Discretionary',
    'MBLY': 'Consumer Discretionary', 'MC': 'Financials', 'MCD': 'Consumer Discretionary', 'MCHP': 'Semiconductors',
    'MCK': 'Healthcare', 'MCO': 'Financials', 'MDB': 'Technology', 'MDGL': 'Biotech',
    'MDLN': 'Healthcare', 'MDLZ': 'Consumer Staples', 'MDT': 'Healthcare', 'MEDP': 'Healthcare',
    'MELI': 'Consumer Discretionary', 'MET': 'Financials', 'META': 'Communication Services', 'METC': 'Materials',
    'MFC': 'Financials', 'MGA': 'Consumer Discretionary', 'MGM': 'Consumer Discretionary', 'MGY': 'Energy',
    'MHK': 'Consumer Discretionary', 'MIDD': 'Industrials', 'MIR': 'Industrials', 'MIRM': 'Biotech',
    'MKC': 'Consumer Staples', 'MKL': 'Financials', 'MKSI': 'Technology', 'MKTX': 'Financials',
    'MLI': 'Industrials', 'MLM': 'Materials', 'MLTX': 'Biotech', 'MMM': 'Industrials',
    'MMSI': 'Healthcare', 'MMYT': 'Consumer Discretionary', 'MNDY': 'Technology', 'MNST': 'Consumer Staples',
    'MNTS': 'Industrials', 'MO': 'Consumer Staples', 'MOD': 'Consumer Discretionary', 'MOH': 'Healthcare',
    'MORN': 'Financials', 'MOS': 'Materials', 'MP': 'Materials', 'MPC': 'Energy',
    'MPWR': 'Technology', 'MRCY': 'Industrials', 'MRK': 'Healthcare', 'MRNA': 'Healthcare',
    'MRSH': 'Financials', 'MRVL': 'Technology', 'MS': 'Financials', 'MSCI': 'Financials',
    'MSFT': 'Technology', 'MSGS': 'Communication Services', 'MSI': 'Technology', 'MSM': 'Industrials',
    'MSTR': 'Technology', 'MT': 'Materials', 'MTB': 'Financials', 'MTCH': 'Communication Services',
    'MTD': 'Healthcare', 'MTDR': 'Energy', 'MTG': 'Financials', 'MTH': 'Consumer Discretionary',
    'MTN': 'Consumer Discretionary', 'MTSI': 'Technology', 'MTZ': 'Industrials', 'MU': 'Technology',
    'MUFG': 'Financials', 'MUR': 'Energy', 'MUSA': 'Consumer Discretionary', 'NAMM': 'Materials',
    'NBIS': 'Communication Services', 'NBIX': 'Healthcare', 'NCLH': 'Consumer Discretionary', 'NDAQ': 'Financials',
    'NDSN': 'Industrials', 'NE': 'Energy', 'NEE': 'Utilities', 'NEM': 'Materials',
    'NET': 'Technology', 'NEU': 'Materials', 'NFG': 'Energy', 'NFLX': 'Communication Services',
    'NGD': 'Materials', 'NI': 'Utilities', 'NKE': 'Consumer Discretionary', 'NLY': 'Real Estate',
    'NNE': 'Industrials', 'NNN': 'Real Estate', 'NOC': 'Industrials', 'NOV': 'Energy',
    'NOVT': 'Technology', 'NOW': 'Technology', 'NRG': 'Utilities', 'NSA': 'Real Estate',
    'NSC': 'Industrials', 'NTAP': 'Technology', 'NTLA': 'Biotech', 'NTNX': 'Technology',
    'NTR': 'Materials', 'NTRA': 'Healthcare', 'NTRS': 'Financials', 'NU': 'Financials',
    'NUE': 'Materials', 'NUGT': 'Materials', 'NUVL': 'Healthcare', 'NVDA': 'Technology',
    'NVMI': 'Technology', 'NVO': 'Healthcare', 'NVR': 'Consumer Discretionary', 'NVS': 'Healthcare',
    'NVST': 'Healthcare', 'NVT': 'Industrials', 'NVTS': 'Semiconductors', 'NWSA': 'Communication Services',
    'NXE': 'Energy', 'NXPI': 'Semiconductors', 'NXST': 'Communication Services', 'NXT': 'Technology',
    'NYT': 'Communication Services', 'O': 'Real Estate', 'OC': 'Industrials', 'OCUL': 'Healthcare',
    'ODFL': 'Logistics', 'OGE': 'Utilities', 'OGN': 'Healthcare', 'OHI': 'Real Estate',
    'OIH': 'Energy', 'OKE': 'Energy', 'OKLO': 'Utilities', 'OKTA': 'Technology',
    'OLED': 'Technology', 'OLLI': 'Consumer Staples', 'OLN': 'Materials', 'OMC': 'Communication Services',
    'OMER': 'Healthcare', 'OMF': 'Financials', 'ON': 'Semiconductors', 'ONB': 'Financials',
    'ONDS': 'Technology', 'ONON': 'Consumer Discretionary', 'ONTO': 'Technology', 'OPCH': 'Healthcare',
    'OPEN': 'Real Estate', 'OR': 'Materials', 'ORA': 'Utilities', 'ORC': 'Real Estate',
    'ORCL': 'Technology', 'ORI': 'Financials', 'ORLY': 'Consumer Discretionary', 'OS': 'Technology',
    'OSCR': 'Healthcare', 'OSIS': 'Technology', 'OSK': 'Industrials', 'OTIS': 'Industrials',
    'OUNZ': 'Materials', 'OVV': 'Energy', 'OWL': 'Financials', 'OXY': 'Energy',
    'OZK': 'Financials', 'PAAS': 'Materials', 'PANW': 'Technology', 'PATH': 'Technology',
    'PAYC': 'Technology', 'PAYX': 'Technology', 'PB': 'Financials', 'PBF': 'Energy',
    'PBR': 'Energy', 'PCAR': 'Industrials', 'PCG': 'Utilities', 'PCOR': 'Technology',
    'PCTY': 'Technology', 'PCVX': 'Healthcare', 'PDI': 'Financials', 'PEG': 'Utilities',
    'PEGA': 'Energy', 'PEN': 'Healthcare', 'PENN': 'Consumer Discretionary', 'PEP': 'Consumer Staples',
    'PFE': 'Healthcare', 'PFG': 'Financials', 'PFGC': 'Consumer Staples', 'PFSI': 'Financials',
    'PG': 'Consumer Staples', 'PGR': 'Financials', 'PGY': 'Technology', 'PH': 'Industrials',
    'PHM': 'Consumer Discretionary', 'PHYS': 'Materials', 'PI': 'Technology', 'PICK': 'Materials',
    'PII': 'Consumer Discretionary', 'PINS': 'Communication Services', 'PKG': 'Consumer Discretionary', 'PL': 'Industrials',
    'PLD': 'Real Estate', 'PLNT': 'Consumer Discretionary', 'PLTR': 'Technology', 'PLUG': 'Industrials',
    'PM': 'Consumer Staples', 'PNC': 'Financials', 'PNFP': 'Financials', 'PNR': 'Industrials',
    'PNW': 'Utilities', 'PODD': 'Healthcare', 'POET': 'Technology', 'POOL': 'Industrials',
    'POST': 'Consumer Staples', 'POWL': 'Industrials', 'PPA': 'Defense', 'PPG': 'Materials',
    'PPL': 'Utilities', 'PPTA': 'Materials', 'PR': 'Energy', 'PRAX': 'Healthcare',
    'PRIM': 'Industrials', 'PRMB': 'Consumer Staples', 'PRU': 'Financials', 'PSA': 'Real Estate',
    'PSKY': 'Communication Services', 'PSLV': 'Materials', 'PSN': 'Technology', 'PSTG': 'Technology',
    'PSX': 'Energy', 'PTC': 'Technology', 'PTCT': 'Biotech', 'PTEN': 'Energy',
    'PTGX': 'Biotech', 'PTON': 'Consumer Discretionary', 'PVH': 'Consumer Discretionary', 'PWR': 'Industrials',
    'PYPL': 'Financials', 'Q': 'Technology', 'QBTS': 'Technology', 'QCOM': 'Technology',
    'QGEN': 'Healthcare', 'QRVO': 'Technology', 'QS': 'Consumer Discretionary', 'QSR': 'Consumer Discretionary',
    'QUBT': 'Technology', 'QXO': 'Industrials', 'R': 'Industrials', 'RACE': 'Consumer Discretionary',
    'RAL': 'Technology', 'RARE': 'Biotech', 'RBA': 'Industrials', 'RBC': 'Industrials',
    'RBLX': 'Communication Services', 'RBRK': 'Technology', 'RCAT': 'Industrials', 'RCL': 'Consumer Discretionary',
    'RDDT': 'Communication Services', 'RDW': 'Industrials', 'REG': 'Real Estate', 'REGN': 'Biotech',
    'REMX': 'Materials', 'REXR': 'Real Estate', 'RF': 'Financials', 'RGA': 'Financials',
    'RGEN': 'Healthcare', 'RGLD': 'Materials', 'RGTI': 'Technology', 'RH': 'Consumer Discretionary',
    'RHI': 'Industrials', 'RIG': 'Energy', 'RIO': 'Materials', 'RIOT': 'Financials',
    'RITM': 'Real Estate', 'RIVN': 'Consumer Discretionary', 'RJF': 'Financials', 'RKLB': 'Industrials',
    'RKT': 'Financials', 'RL': 'Consumer Discretionary', 'RMBS': 'Technology', 'RMD': 'Healthcare',
    'RNA': 'Healthcare', 'RNR': 'Financials', 'ROIV': 'Healthcare', 'ROK': 'Industrials',
    'ROKU': 'Communication Services', 'ROL': 'Consumer Discretionary', 'ROLR': 'Consumer Discretionary', 'ROP': 'Technology',
    'ROST': 'Consumer Discretionary', 'RPM': 'Materials', 'RPRX': 'Healthcare', 'RR': 'Industrials',
    'RRC': 'Energy', 'RRX': 'Industrials', 'RS': 'Materials', 'RSG': 'Industrials',
    'RTX': 'Industrials', 'RUN': 'Technology', 'RVMD': 'Healthcare', 'RVTY': 'Healthcare',
    'RXRX': 'Biotech', 'RY': 'Financials', 'RYAN': 'Financials', 'RYTM': 'Biotech',
    'RZLV': 'Technology', 'S': 'Technology', 'SAIA': 'Industrials', 'SAIC': 'Technology',
    'SANM': 'Technology', 'SAP': 'Technology', 'SARO': 'Industrials', 'SATS': 'Communication Services',
    'SBAC': 'Real Estate', 'SBET': 'Financials', 'SBIT': 'Crypto', 'SBSW': 'Materials',
    'SBUX': 'Consumer Discretionary', 'SCCO': 'Materials', 'SCHW': 'Financials', 'SCI': 'Consumer Discretionary',
    'SEB': 'Industrials', 'SEDG': 'Energy Transition', 'SEE': 'Consumer Discretionary', 'SEI': 'Energy Transition',
    'SERV': 'Industrials', 'SF': 'Financials', 'SFM': 'Consumer Staples', 'SGI': 'Consumer Discretionary',
    'SGML': 'Materials', 'SGOL': 'Materials', 'SHAK': 'Consumer Discretionary', 'SHLD': 'Defense',
    'SHOP': 'Technology', 'SHW': 'Materials', 'SIDU': 'Industrials', 'SIG': 'Consumer Discretionary',
    'SIL': 'Materials', 'SILJ': 'Materials', 'SIRI': 'Communication Services', 'SITE': 'Industrials',
    'SITM': 'Technology', 'SIVR': 'Materials', 'SJM': 'Consumer Staples', 'SKY': 'Consumer Discretionary',
    'SKYT': 'Technology', 'SLB': 'Energy', 'SLM': 'Financials', 'SLNO': 'Biotech',
    'SLS': 'Healthcare', 'SLV': 'Materials', 'SLVP': 'Materials', 'SM': 'Energy',
    'SMCI': 'Technology', 'SMH': 'Semiconductors', 'SMR': 'Industrials', 'SMTC': 'Technology',
    'SMX': 'Industrials', 'SN': 'Consumer Discretionary', 'SNA': 'Industrials', 'SNAP': 'Communication Services',
    'SNDK': 'Technology', 'SNOW': 'Technology', 'SNPS': 'Technology', 'SNX': 'Technology',
    'SO': 'Utilities', 'SOC': 'Energy', 'SOFI': 'Financials', 'SOLS': 'Materials',
    'SOLV': 'Healthcare', 'SOUN': 'Technology', 'SOXL': 'Semiconductors', 'SOXS': 'Semiconductors',
    'SOXX': 'Semiconductors', 'SPG': 'Real Estate', 'SPGI': 'Financials', 'SPHL': 'Consumer Discretionary',
    'SPHR': 'Communication Services', 'SPOT': 'Communication Services', 'SPXC': 'Industrials', 'SQM': 'Materials',
    'SRAD': 'Technology', 'SRE': 'Utilities', 'SRPT': 'Biotech', 'SSB': 'Financials',
    'SSNC': 'Technology', 'SSRM': 'Materials', 'STAG': 'Real Estate', 'STE': 'Healthcare',
    'STLA': 'Consumer Discretionary', 'STLD': 'Materials', 'STM': 'Technology', 'STNE': 'Technology',
    'STNG': 'Energy', 'STRL': 'Industrials', 'STT': 'Financials', 'STWD': 'Real Estate',
    'STX': 'Technology', 'STZ': 'Consumer Staples', 'SU': 'Energy', 'SVM': 'Materials',
    'SW': 'Consumer Discretionary', 'SWK': 'Industrials', 'SWKS': 'Technology', 'SYF': 'Financials',
    'SYK': 'Healthcare', 'SYM': 'Industrials', 'SYNA': 'Technology', 'SYY': 'Consumer Staples',
    'T': 'Communication Services', 'TAN': 'Energy Transition', 'TAP': 'Consumer Staples', 'TD': 'Financials',
    'TDG': 'Industrials', 'TDY': 'Technology', 'TE': 'Industrials', 'TEAM': 'Technology',
    'TECH': 'Healthcare', 'TECK': 'Materials', 'TEL': 'Technology', 'TEM': 'Healthcare',
    'TER': 'Technology', 'TERN': 'Biotech', 'TEX': 'Industrials', 'TFC': 'Financials',
    'TFX': 'Healthcare', 'TGB': 'Materials', 'TGT': 'Consumer Staples', 'TGTX': 'Biotech',
    'THC': 'Healthcare', 'THG': 'Financials', 'THO': 'Consumer Discretionary', 'TIGO': 'Communication Services',
    'TJX': 'Consumer Discretionary', 'TKO': 'Communication Services', 'TKR': 'Industrials', 'TLN': 'Utilities',
    'TLRY': 'Healthcare', 'TM': 'Consumer Discretionary', 'TMC': 'Materials', 'TMDX': 'Healthcare',
    'TMHC': 'Consumer Discretionary', 'TMO': 'Healthcare', 'TMUS': 'Communication Services', 'TOL': 'Consumer Discretionary',
    'TOST': 'Technology', 'TPG': 'Financials', 'TPL': 'Energy', 'TPR': 'Consumer Discretionary',
    'TREX': 'Industrials', 'TRGP': 'Energy', 'TRI': 'Industrials', 'TRMB': 'Technology',
    'TROW': 'Financials', 'TRP': 'Energy', 'TRU': 'Financials', 'TRV': 'Financials',
    'TSCO': 'Consumer Discretionary', 'TSEM': 'Semiconductors', 'TSLA': 'Consumer Discretionary', 'TSM': 'Semiconductors',
    'TSN': 'Consumer Staples', 'TT': 'Industrials', 'TTAN': 'Technology', 'TTC': 'Industrials',
    'TTD': 'Communication Services', 'TTE': 'Energy', 'TTEK': 'Industrials', 'TTMI': 'Technology',
    'TTWO': 'Communication Services', 'TU': 'Communication Services', 'TVTX': 'Biotech', 'TW': 'Financials',
    'TWLO': 'Technology', 'TXN': 'Technology', 'TXRH': 'Consumer Discretionary', 'TXT': 'Industrials',
    'TYL': 'Technology', 'UAA': 'Consumer Discretionary', 'UBER': 'Technology', 'UBS': 'Financials',
    'UCO': 'Energy', 'UDR': 'Real Estate', 'UEC': 'Energy', 'UGI': 'Utilities',
    'UGL': 'Materials', 'UHS': 'Healthcare', 'UI': 'Technology', 'ULS': 'Industrials',
    'ULTA': 'Consumer Discretionary', 'UMAC': 'Technology', 'UMBF': 'Financials', 'UNG': 'Energy',
    'UNM': 'Financials', 'UNP': 'Industrials', 'UPST': 'Financials', 'URBN': 'Consumer Discretionary',
    'USAR': 'Materials', 'USB': 'Financials', 'USFD': 'Consumer Staples', 'USO': 'Energy',
    'UUUU': 'Energy', 'UWMC': 'Financials', 'V': 'Financials', 'VAL': 'Energy',
    'VEEV': 'Healthcare', 'VERA': 'Biotech', 'VERO': 'Healthcare', 'VFC': 'Consumer Discretionary',
    'VG': 'Energy', 'VIAV': 'Technology', 'VICI': 'Real Estate', 'VICR': 'Technology',
    'VIK': 'Consumer Discretionary', 'VISN': 'Technology', 'VKTX': 'Biotech', 'VLO': 'Energy',
    'VLTO': 'Industrials', 'VLY': 'Financials', 'VMC': 'Materials', 'VMI': 'Industrials',
    'VNOM': 'Energy', 'VOYA': 'Financials', 'VOYG': 'Industrials', 'VRNS': 'Technology',
    'VRSK': 'Industrials', 'VRSN': 'Technology', 'VRT': 'Industrials', 'VRTX': 'Biotech',
    'VSAT': 'Technology', 'VSCO': 'Consumer Discretionary', 'VSEC': 'Industrials', 'VSNT': 'Communication Services',
    'VST': 'Utilities', 'VTR': 'Real Estate', 'VTRS': 'Healthcare', 'VVV': 'Consumer Discretionary',
    'VZ': 'Communication Services', 'W': 'Consumer Discretionary', 'WAB': 'Industrials', 'WAL': 'Financials',
    'WAT': 'Healthcare', 'WAY': 'Healthcare', 'WBD': 'Communication Services', 'WBS': 'Financials',
    'WCC': 'Industrials', 'WCN': 'Industrials', 'WDAY': 'Technology', 'WDC': 'Technology',
    'WEC': 'Utilities', 'WELL': 'Real Estate', 'WFC': 'Financials', 'WFRD': 'Energy',
    'WGS': 'Healthcare', 'WH': 'Consumer Discretionary', 'WHR': 'Consumer Discretionary', 'WINA': 'Consumer Discretionary',
    'WING': 'Consumer Discretionary', 'WIX': 'Technology', 'WK': 'Technology', 'WLK': 'Materials',
    'WM': 'Industrials', 'WMB': 'Energy', 'WMG': 'Communication Services', 'WMS': 'Industrials',
    'WMT': 'Consumer Staples', 'WPC': 'Real Estate', 'WPM': 'Materials', 'WRB': 'Financials',
    'WRBY': 'Healthcare', 'WSM': 'Consumer Discretionary', 'WSO': 'Industrials', 'WST': 'Biotech',
    'WT': 'Financials', 'WTFC': 'Financials', 'WTRG': 'Utilities', 'WTW': 'Financials',
    'WU': 'Financials', 'WULF': 'Financials', 'WVE': 'Healthcare', 'WWD': 'Industrials',
    'WY': 'Real Estate', 'WYNN': 'Consumer Discretionary', 'XAR': 'Defense', 'XBI': 'Biotech',
    'XEL': 'Utilities', 'XME': 'Materials', 'XOM': 'Energy', 'XOP': 'Energy',
    'XP': 'Financials', 'XPO': 'Industrials', 'XYL': 'Industrials', 'XYZ': 'Technology',
    'YETI': 'Consumer Discretionary', 'YUM': 'Consumer Discretionary', 'Z': 'Communication Services', 'ZBH': 'Healthcare',
    'ZBRA': 'Technology', 'ZETA': 'Technology', 'ZG': 'Communication Services', 'ZIM': 'Industrials',
    'ZION': 'Financials', 'ZM': 'Technology', 'ZS': 'Technology', 'ZSL': 'Materials',
    'ZTS': 'Healthcare',
}


# ── CORS ──────────────────────────────────────────────────────────────────────

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    # Chrome 104+ Private Network Access — required for HTTPS pages
    # (like the GitHub Pages dashboard) to reach localhost. Without
    # this the preflight succeeds but the browser silently blocks the
    # actual request before it ever shows up in the network panel.
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.route("/api/ping", methods=["OPTIONS"])
@app.route("/api/ticker", methods=["OPTIONS"])
@app.route("/api/quote", methods=["OPTIONS"])
@app.route("/api/sim/log", methods=["OPTIONS"])
@app.route("/api/sim/feed", methods=["OPTIONS"])
def _options():
    return "", 200


# ── Sim-desk intern telemetry ─────────────────────────────────────────────────
# The paper-trading simulator posts trade and daily-snapshot events here so the
# owner can watch activity and build daily reports ON THIS MACHINE. Append-only
# JSONL with size-capped fields; paper trades only, nothing sensitive, and the
# log never leaves this box.
SIM_LOG_PATH = r"C:\Portfolizer\sim-logs\events.jsonl"


@app.route("/api/sim/log", methods=["POST"])
def sim_log():
    import json as _json
    try:
        evt = request.get_json(force=True, silent=True) or {}
        rec = {
            "received": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
            "trader":   str(evt.get("trader", "intern"))[:40],
            "type":     str(evt.get("type", "?"))[:20],
        }
        for k in ("t", "side", "qty", "px", "value", "cash", "total",
                  "spy", "as_of", "ts"):
            if k in evt:
                v = evt[k]
                rec[k] = v[:40] if isinstance(v, str) else v
        os.makedirs(os.path.dirname(SIM_LOG_PATH), exist_ok=True)
        with open(SIM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec) + "\n")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sim/feed", methods=["GET"])
def sim_feed():
    """Read-back of the intern telemetry for the supervisor dashboard.

    Returns the most recent events (paper-trading only). Read-only — it never
    writes — reading the same append-only log the POST handler above appends to.
    The dashboard (a GitHub Pages page) reaches this through the same tunnel the
    intern's app uses; CORS is handled globally by _cors().
    """
    import json as _json
    try:
        limit = min(max(int(request.args.get("limit", 2000)), 1), 10000)
    except Exception:
        limit = 2000
    events = []
    if os.path.exists(SIM_LOG_PATH):
        try:
            with open(SIM_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(_json.loads(line))
            except Exception:
                continue
    return jsonify({"ok": True, "count": len(events),
                    "server_time": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
                    "events": events})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_naive_index(index):
    """Return a tz-naive DatetimeIndex regardless of whether input has a timezone."""
    idx = pd.to_datetime(index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx


# ── SPY features ──────────────────────────────────────────────────────────────

def _fetch_spy():
    hist = yf.Ticker("SPY").history(period="5y", auto_adjust=True)
    if hist.empty or len(hist) < 150:
        raise ValueError("Insufficient SPY data from yfinance")
    close = hist["Close"]
    spy = pd.DataFrame({"close": close.values}, index=_to_naive_index(close.index))
    spy["return_5"] = spy["close"].pct_change(5)
    spy["return_20"] = spy["close"].pct_change(20)
    spy["volatility"] = spy["close"].pct_change().rolling(20).std()
    rolling_max = spy["close"].rolling(60).max()
    spy["drawdown"] = (spy["close"] - rolling_max) / rolling_max
    return spy.dropna()


def _compute_analog_dates(spy_df):
    vec = np.array([spy_df.iloc[-1][c] for c in ["return_5", "return_20", "volatility", "drawdown"]])
    hist = spy_df.iloc[:-EXCLUDE_RECENT_DAYS].copy()
    cols = ["return_5", "return_20", "volatility", "drawdown"]
    hist["dist"] = hist[cols].apply(lambda r: float(np.linalg.norm(r.values - vec)), axis=1)
    similar = hist.nsmallest(SIMILAR_DAY_COUNT, "dist")
    return set(similar.index.strftime("%Y-%m-%d"))


def _restricted_analog_dates(spy_df, ticker_start, count=20):
    """Find best SPY analog days within a recently-listed ticker's date range."""
    vec = np.array([spy_df.iloc[-1][c] for c in ["return_5", "return_20", "volatility", "drawdown"]])
    cutoff = spy_df.index[-EXCLUDE_RECENT_DAYS]
    cols = ["return_5", "return_20", "volatility", "drawdown"]
    hist = spy_df[(spy_df.index >= ticker_start) & (spy_df.index <= cutoff)].copy()
    if len(hist) < 3:
        return set()
    hist["dist"] = hist[cols].apply(lambda r: float(np.linalg.norm(r.values - vec)), axis=1)
    similar = hist.nsmallest(min(count, len(hist)), "dist")
    return set(similar.index.strftime("%Y-%m-%d"))


def _ensure_spy():
    """Return (spy_df, analog_dates), fetched once per calendar day."""
    with _state["lock"]:
        today = str(date.today())
        if _state["last_refresh"] == today and _state["spy_df"] is not None:
            return _state["spy_df"], _state["analog_dates"]
        print("[api] Fetching SPY from yfinance...", flush=True)
        spy_df = _fetch_spy()
        analog_dates = _compute_analog_dates(spy_df)
        _state["spy_df"] = spy_df
        _state["analog_dates"] = analog_dates
        _state["last_refresh"] = today
        _state["ticker_cache"] = {}
        print(f"[api] SPY ready — {len(analog_dates)} analog dates", flush=True)
        return spy_df, analog_dates


# ── Signal computation ────────────────────────────────────────────────────────

def _signal_for_dates(prices, analog_dates, ticker, med_vol, min_obs, short_history=False):
    """Return {label: signal_dict} for every horizon that meets min_obs."""
    results = {}
    for label, days in HORIZONS.items():
        future = prices["close"].shift(-days) / prices["close"] - 1
        valid = prices.assign(fr=future).dropna(subset=["fr"])
        if len(valid) < 10:
            continue
        baseline = float(valid["fr"].median())
        analog_rows = valid[valid["ds"].isin(analog_dates)]
        n = len(analog_rows)
        if n < min_obs:
            continue
        vals = analog_rows["fr"].values
        cond = float(np.median(vals))
        edge = round(cond - baseline, 4)
        pcts = np.percentile(vals, [10, 25, 50, 75, 90])
        hit = round(float((vals > 0).mean()), 3)
        results[label] = {
            "edge":            edge,
            "n_obs":           n,
            "p10":             round(float(pcts[0]), 4),
            "p25":             round(float(pcts[1]), 4),
            "p50":             round(float(pcts[2]), 4),
            "p75":             round(float(pcts[3]), 4),
            "p90":             round(float(pcts[4]), 4),
            "hit_rate":        hit,
            "vol":             round(med_vol, 4),
            "below_threshold": edge < 0.05,
            "short_history":   short_history,
        }
    return results


def _compute_ticker(ticker):
    spy_df, analog_dates = _ensure_spy()

    cache_key = f"{ticker}:{_state['last_refresh']}"
    if cache_key in _state["ticker_cache"]:
        return _state["ticker_cache"][cache_key]

    hist = yf.Ticker(ticker).history(period="5y", auto_adjust=True)
    if hist.empty or len(hist) < 30:
        return None

    close = hist["Close"]
    daily_ret = close.pct_change()
    vol = daily_ret.rolling(20).std()

    prices = pd.DataFrame({
        "date": _to_naive_index(close.index),
        "close": close.values,
        "volatility": vol.values,
    }).dropna(subset=["close"]).reset_index(drop=True)
    prices = prices.drop_duplicates(subset=["date"]).reset_index(drop=True)
    prices["ds"] = prices["date"].dt.strftime("%Y-%m-%d")
    med_vol = float(prices["volatility"].median())

    horizons = _signal_for_dates(prices, analog_dates, ticker, med_vol, MIN_OBSERVATIONS)
    short_history = False
    if not horizons:
        restricted = _restricted_analog_dates(spy_df, prices["date"].min())
        if restricted:
            horizons = _signal_for_dates(prices, restricted, ticker, med_vol,
                                          min_obs=3, short_history=True)
            short_history = bool(horizons)

    if not horizons:
        _state["ticker_cache"][cache_key] = None
        return None

    recent = [round(float(v), 2) for v in close.values[-7:]]
    best_edge = max(h["edge"] for h in horizons.values())

    result = {
        "ticker":          ticker,
        "name":            ticker,
        "sector":          _SECTOR_MAP.get(ticker, "Unknown"),
        "from_watchlist":  True,
        "short_history":   short_history,
        "below_threshold": best_edge < 0.05,
        "source":          "cloud",
        "horizons":        horizons,
    }
    if len(recent) >= 2:
        result["week_closes"] = recent
        result["price"]       = recent[-1]
        result["change_pct"]  = round((recent[-1] - recent[-2]) / recent[-2], 4)

    _state["ticker_cache"][cache_key] = result
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    spy_ready = _state["spy_df"] is not None
    return jsonify({"ok": True, "source": "cloud", "port": 0, "spy_ready": spy_ready})


@app.route("/api/quote")
def quote():
    t = re.sub(r"[^A-Z0-9.]", "", request.args.get("t", "").strip().upper())
    if not t:
        return jsonify({"error": "missing ?t=TICKER"}), 400
    cache_key = f"quote:{t}:{date.today()}"
    if cache_key in _state["ticker_cache"]:
        return jsonify(_state["ticker_cache"][cache_key])
    try:
        hist = yf.Ticker(t).history(period="12d", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return jsonify({"error": "insufficient data"}), 404
        closes = [round(float(v), 2) for v in hist["Close"].values]
        prev = closes[-2]
        curr = closes[-1]
        result = {
            "ticker": t,
            "price": curr,
            "prev_close": prev,
            "change_pct": round((curr - prev) / prev, 4),
            "week_closes": closes[-7:],
        }
        _state["ticker_cache"][cache_key] = result
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/ticker")
def ticker():
    t = re.sub(r"[^A-Z0-9.]", "", request.args.get("t", "").strip().upper())
    if not t:
        return jsonify({"error": "missing ?t=TICKER"}), 400
    print(f"[api] Computing {t}...", flush=True)
    try:
        signal = _compute_ticker(t)
    except Exception as exc:
        print(f"[api] {t}: ERROR — {exc}", flush=True)
        return jsonify({"error": f"computation failed: {exc}"}), 500
    if signal:
        flag = " [below threshold]" if signal["below_threshold"] else ""
        edges = ", ".join(f"{lbl}:{h['edge']:+.0%}(n={h['n_obs']})"
                          for lbl, h in signal.get("horizons", {}).items())
        print(f"[api] {t}: {edges}{flag}", flush=True)
        return jsonify(signal)
    print(f"[api] {t}: not found or insufficient data", flush=True)
    return jsonify({"error": f"{t} not found or insufficient data"}), 404


# ── Warmup — runs immediately when module is imported (gunicorn or direct) ────

def _warmup():
    try:
        _ensure_spy()
        print("[api] Warmup complete.", flush=True)
    except Exception as exc:
        print(f"[api] Warmup failed: {exc}", flush=True)


threading.Thread(target=_warmup, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[api] Regime Desk Cloud API -> http://0.0.0.0:{port}", flush=True)
    # Use waitress (production-grade pure-Python WSGI server) instead of
    # Flask's dev server. The dev server crashed intermittently on Windows
    # under cross-origin preflight traffic with no traceback — waitress is
    # stable, handles concurrent connections cleanly, and falls back to
    # Flask's dev server only if waitress isn't installed.
    try:
        from waitress import serve
        print(f"[api] Serving with waitress on port {port}", flush=True)
        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        print("[api] waitress not installed; falling back to Flask dev server", flush=True)
        app.run(host="0.0.0.0", port=port, threaded=False)
