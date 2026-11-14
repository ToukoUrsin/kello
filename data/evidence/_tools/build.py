# Builds data/evidence/{parameters,interventions,roadmap_measures}.json
# Every quote below was copied from a page/PDF saved under data/raw/evidence/<slug>/ on 2026-11-13.
# verified=True  -> source text was opened and the quote is in the saved copy (check_quotes() asserts this)
# verified=False -> source could not be opened (403/429) or the figure is not in the opened text
import json, re, os
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[3])
RAW = ROOT + '/data/raw/evidence'
OUT = ROOT + '/data/evidence'
FETCHED = '2026-11-13'
CHECKS = []  # (slug, quote)


def src(slug, url, quote, year, verified=True, access='full_text', **kw):
    d = dict(url=url, quote=quote, year=year, verified=verified, access=access, fetched_at=FETCHED, local_copy=f'data/raw/evidence/{slug}/page.txt' if slug else None)
    d.update(kw)
    if verified and slug:
        CHECKS.append((slug, quote))
    return d


def P(value, lo, hi, kind, s, **kw):
    d = dict(value=value, lo=lo, hi=hi, kind=kind)
    d.update(s)
    d.update(kw)
    return d


U = dict(
    yle_mot='https://yle.fi/a/74-20242733',
    yle2='https://yle.fi/a/74-20250979',
    ihe='https://ihe.se/app/uploads/2026/04/IHE-Cancer-Dashboard-Finland_.pdf',
    khalife='https://pmc.ncbi.nlm.nih.gov/articles/PMC12160590/',
    paappanen='https://pmc.ncbi.nlm.nih.gov/articles/PMC12305687/',
    hanna='https://pmc.ncbi.nlm.nih.gov/articles/PMC7610021/',
    thl='https://www.julkari.fi/server/api/core/bitstreams/de33d584-bdce-40a1-b100-df48c4906a49/content',
    no='https://www.helsedirektoratet.no/nasjonale-forlop/lungekreft/forlopstider-i-pakkeforlop-for-lungekreft',
    se='https://kunskapsbanken.cancercentrum.se/diagnoser/lungcancer/vardforlopp/',
    dk='https://lungekraeft.com/wp-content/uploads/2016/11/pakkeforloeb-for-lungekraeft-sundhedsstyrrelsen.pdf',
    dk_new='https://www.sst.dk/media/estk2oo1/pakkeforloeb-for-lungekraeft-jan-2025.pdf',
    syopaj='https://www.syopajarjestot.fi/uutinen/keuhkosyovan-toteamisessa-on-eroja-hyvinvointialueiden-valilla-tietojen-kattavuudessa-edelleen-parannettavaa/',
    laakarilehti='https://www.laakarilehti.fi/terveydenhuolto/keuhkosyovan-toteamisessa-eroja-hyvinvointialueiden-valilla/',
    zai='https://pmc.ncbi.nlm.nih.gov/articles/PMC12551501/',
    ostro='https://pmc.ncbi.nlm.nih.gov/articles/PMC11332544/',
    jensen='https://pmc.ncbi.nlm.nih.gov/articles/PMC5585953/',
    svf='https://pmc.ncbi.nlm.nih.gov/articles/PMC10636179/',
    radiox='https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10447363/',
    gpct='https://pmc.ncbi.nlm.nih.gov/articles/PMC4660800/',
    lungimpact='https://www.nature.com/articles/s41591-026-04253-5',
    reflex='https://doi.org/10.1093/jalm/jfad104',
    accelerate='https://pmc.ncbi.nlm.nih.gov/articles/PMC10369925/',
    navigator='https://pmc.ncbi.nlm.nih.gov/articles/PMC13457979/',
    ldct='https://pmc.ncbi.nlm.nih.gov/articles/PMC8589726/',
    nelson='https://doi.org/10.1056/NEJMoa1911793',
    nhs='https://www.england.nhs.uk/2024/11/thousands-of-cancers-caught-early-through-nhs-lung-checks/',
    yle_ldct='https://yle.fi/a/74-20205604',
    bcoc='https://pmc.ncbi.nlm.nih.gov/articles/PMC4453621/',
    lungboost='https://pmc.ncbi.nlm.nih.gov/articles/PMC4648022/',
    nssc='https://pmc.ncbi.nlm.nih.gov/articles/PMC10773629/',
    cessation='https://doi.org/10.7326/M21-0252',
    tyks='https://www.tyks.fi/potilaille-ja-laheisille/hoidot-ja-tutkimukset/syopa/keuhkosyovan-hoitoonpaasyajat',
    fcr='https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html',
    thl_unit='https://thl.fi/data-ja-tilastot/sote-talous/yksikkokustannukset',
    roadmap='res/roadmap/r.txt',
    strategy='res/strategy/s.txt',
)

# ---------------------------------------------------------------- parameters
Q_MOT_STEPS = 'Tutkimuksen perusteella potilaasta itsestään johtuva viive on yli 50 päivää, perusterveydenhuollossa kuluu 41 päivää ja erikoissairaanhoidossa 58 päivää.'
Q_MOT_155 = 'Ylen MOT kertoi, että syövän hoidossa takamatka länsinaapureihin on pitkä. Tanskassa keuhkosyöpäpotilas pääsee hoitoon 67 päivässä. Ruotsissa viive ensimmäisten oireiden toteamisen jälkeen on 107 päivää. Suomessa viive on pisin, 155 päivää.'
Q_KHALIFE_T2 = 'For specialist consultation after initial visit to a GP (weeks)                          2–4       1–2       1–2      1–2       2–3'
Q_KHALIFE_DX = 'For a LC diagnosis after specialist consultation (weeks)                                  4         4        2–4      2–4       1–2'
Q_IHE_3638 = 'time from diagnosis to start of treatment for patients treated during the first six months was 36–38 days in 2018-'

split_method = ('Yle MOT gives one figure for specialist care (58 days). No opened source gives a measured Finnish split of it. '
                'We split 58 days in proportion to three published Finnish figures that describe the same three sub-steps but do not add up to 58: '
                'GP visit -> specialist consultation 2-4 weeks (mid 21 d, Khalife 2025 survey mode), specialist consultation -> diagnosis 4 weeks (28 d, Khalife 2025), '
                'diagnosis -> treatment start 36-38 days (37 d, Finnish Cancer Registry 2018-2022 via IHE 2026). Weights 21:28:37 -> 14, 19, 25 days. '
                'lo/hi use the Khalife range for referral (2-4 weeks scaled) and +-30 % for the others. The unscaled figures sum to 86 days, i.e. the specialist phase may be longer than the 58 days Yle reports.')

parameters = {
    '_meta': {
        'built_at': FETCHED,
        'owner': 'evidence agent',
        'rules': 'verified=true means the source page or PDF was opened on the fetch date and the quote is present in the saved copy under data/raw/evidence/. access=abstract means only the publisher abstract (via Europe PMC) was opened. kind: measured = copied from a published source; reported = a figure a journalist reported from a study that is not published (no sample size, no method), shown as reported and never as measured; estimated = our arithmetic on measured figures (method given); assumption = set by us, editable.',
        'sign_convention': 'In interventions.json effect values for metric days / relative_days are days SAVED (positive = faster). relative_days is the fraction of the interval removed. stage_shift_pp = percentage-point rise in stage I share. mortality_rr < 1 = fewer deaths.',
    },
    'baseline_days': {
        'source_study': {
            'description_en': 'Unpublished ongoing Finnish study of lung cancer treatment delays, coordinated by Professor Outi Kuittinen (University of Eastern Finland), run in Kuopio, Tampere, Turku and Rovaniemi. First results given to Yle MOT (published 12 Oct 2026). Sample size and whether figures are means or medians are not stated in the article text ("keskimäärin").',
            'cities': ['Kuopio', 'Tampere', 'Turku', 'Rovaniemi'],
            'sample_size': None,
            'sample_size_note': 'Not stated in the article text; the infographic could not be read as text.',
            **src('yle_mot', U['yle_mot'], 'Onkologian professori Outi Kuittinen Itä-Suomen yliopistosta koordinoi käynnissä olevaa tutkimusta keuhkosyöpähoitojen viiveistä. Sitä tehdään Kuopiossa, Tampereella, Turussa ja Rovaniemellä.', 2026),
        },
        'total': P(155, 149, 165, 'reported', src('yle_250979', U['yle2'], Q_MOT_155, 2026),
                   note='155 days is stated in the Yle follow-up article (and the MOT infographic); the MOT article text says "keskimäärin noin viisi kuukautta". lo = 50+41+58; hi is our assumption.'),
        'steps': {
            'patient': P(56, 50, 65, 'estimated', src('yle_mot', U['yle_mot'], Q_MOT_STEPS, 2026),
                         method='Source says "over 50 days". 56 = 155 total - 41 primary care - 58 specialist care. lo = 50 (stated floor), hi = assumption.',
                         definition='first symptom -> first primary care contact ("potilaasta itsestään johtuva viive")'),
            'primary': P(41, 33, 49, 'reported', src('yle_mot', U['yle_mot'], Q_MOT_STEPS, 2026),
                         method='Point value from source. No interval published; lo/hi = +-20 % assumption.',
                         definition='time spent in primary care before referral ("perusterveydenhuollossa kuluu 41 päivää")'),
            'referral': P(14, 9, 19, 'estimated', src('khalife', U['khalife'], Q_KHALIFE_T2, 2025), method=split_method,
                          definition='referral -> first specialist visit'),
            'diagnosis': P(19, 13, 25, 'estimated', src('khalife', U['khalife'], Q_KHALIFE_DX, 2025), method=split_method,
                           definition='first specialist visit -> diagnosis and treatment decision'),
            'treatment': P(25, 17, 37, 'estimated', src('ihe_pdf', U['ihe'], Q_IHE_3638, 2026), method=split_method,
                           definition='treatment decision -> treatment start',
                           note='The registry figure (36-38 days median, diagnosis -> treatment start, 2018-2022) is the only national measured number for any specialist sub-step; hi = 37 keeps it inside the interval. IHE cites: Malila et al., Lung cancer report, Cancer Society of Finland 2024 (primary report not opened).'),
        },
        'specialist_total': P(58, 46, 86, 'reported', src('yle_mot', U['yle_mot'], Q_MOT_STEPS, 2026),
                              note='hi = 86 = sum of unscaled Khalife + registry figures (21+28+37).'),
        'supporting': [
            src('khalife', U['khalife'], 'To secure an appointment at the health center for patients with LC symptoms (days)       14        2–7       2–7      2–7       2–7', 2025,
                claim='Survey mode: 14 days to get a health-centre appointment with lung cancer symptoms in Finland vs 2-7 days in Sweden, Denmark, Norway, Iceland.', design='survey of healthcare professionals + expert workshops'),
            src('khalife', U['khalife'], 'Mode of reported share of patients meeting a doctor in the first healthcare contact    40–60%    80–100%    100%      100%     100%', 2025,
                claim='In Finland 40-60 % of patients meet a doctor at first contact vs 80-100 % elsewhere in the Nordics.', design='survey'),
            src('khalife', U['khalife'], 'In 2023, 35% of patients waited longer than 14 days to see a doctor in primary care, and 14% waited for 1–3 months', 2025,
                claim='National primary care waiting data 2023 (not lung-specific).', design='national statistics cited in paper'),
            src('yle_mot', U['yle_mot'], 'Erikoissairaanhoidossa on taas odottamista esimerkiksi kuvaukseen, kuvauslausuntoon ja näytteenottoon.', 2026,
                claim='Where specialist-care time goes: waiting for imaging, the imaging report and biopsy.'),
        ],
    },
    'measured_hospital_times': [
        {'area_id': '05', 'hospital': 'Tyks (Turku University Hospital)', 'referral_to_first_visit_days': None, 'referral_to_treatment_days': None, 'period': None, 'kind': 'measured',
         **src(None, U['tyks'], None, None, verified=False, access='blocked_403', note='Tyks publishes lung cancer access times on this page, but it returned HTTP 403 to curl, WebFetch and two proxies on 2026-11-13. Values left empty rather than filled from memory. Open in a browser and enter the numbers.')},
    ],
    'measured_hospital_times_note': 'No per-hospital lung cancer times could be opened. IHE 2026 states: "Some wellbeing services counties publish their own statistics online, but they group all cancers together with no split by cancer type". The Finnish Cancer Registry lung report 2019-2023 (' + U['fcr'] + ') was later opened from the copy the data agent saved (data/raw/evidence/fcr_report/page.txt).',
    'nordic_benchmarks_total_days': {
        'definition': 'first symptom -> treatment start, lung cancer, as reported by Yle MOT (method of the Swedish and Danish figures is not described in the article)',
        'FI': P(155, None, None, 'measured', src('yle_250979', U['yle2'], Q_MOT_155, 2026)),
        'SE': P(107, None, None, 'measured', src('yle_mot', U['yle_mot'], 'Ruotsissa vastaava kokonaisviive on 107 vuorokautta. Tanskassa se on 67 vuorokautta, eli useita kuukausia vähemmän.', 2026)),
        'DK': P(67, None, None, 'measured', src('yle_mot', U['yle_mot'], 'Ruotsissa vastaava kokonaisviive on 107 vuorokautta. Tanskassa se on 67 vuorokautta, eli useita kuukausia vähemmän.', 2026)),
    },
    'target_times': {
        'FI_thl_ohjaus_21_2016': {
            'referral_to_first_treatment': P(42, None, None, 'measured', src('thl_b1', U['thl'], 'teen saapumisesta ensimmäiseen hoitoon (leikkaus, lääke- tai sädehoito) on 6 viikkoa.', 2016),
                                             note='"Syöpäepäilyssä maksimiaika lähetteen saapumisesta ensimmäiseen hoitoon ... on 6 viikkoa" = 42 days. This is the target the National Cancer Strategy indicator "Potilaat pääsevät hoitoon tavoiteaikojen puitteissa" points to. The PDF opened is the version "Voimassa 1.1.2017 lähtien" (file name ...päivitys170225).'),
            'imaging_report': P(7, None, None, 'measured', src('thl_b1', U['thl'], 'olla käytettävissä viikon kuluessa tutkimuspyynnön tekemisestä.', 2016), note='Radiologist report within one week of the imaging request.'),
            'biopsy': P(7, None, None, 'measured', src('thl_b1', U['thl'], 'biopsia tai neulanäyte) tulee ottaa viikon kuluessa tutkimuspyynnön saapumisesta kirurgiseen yksikköön tai', 2016), note='Tissue sample within one week of the request.'),
            'pathology_report': P(7, None, None, 'measured', src('thl_b1', U['thl'], 'kuvantamisyksikköön. Patologin lausunnon tulee olla käytettävissä viikon kuluessa kudosnäytteen otosta,', 2016), note='Pathology report within one week of the sample, unless special stains are needed.'),
            'referral_to_first_visit': P(21, None, None, 'measured', src('ihe_pdf', U['ihe'], 'the need for treatment must begin within 21 days of the referral arriving at the hospital or other unit providing', 2026),
                                         note='Not a cancer-specific THL Ohjaus target: the general statutory limit (assessment of need for treatment within 21 days of referral), as described by IHE 2026. THL Ohjaus 21/2016 gives no separate referral -> first visit or referral -> treatment decision limit in the text we opened.'),
            'referral_to_treatment_decision': P(None, None, None, 'measured', src(None, U['thl'], None, 2016, verified=False, note='No such limit found in the opened PDF.')),
            'statutory_treatment_start': P(180, None, None, 'measured', src('ihe_pdf', U['ihe'], 'specialized medical care in the hospital district, and the necessary treatment must begin within 180 days of the', 2026)),
        },
        'NO_pakkeforlop_lung': {
            'referral_to_first_visit': P(7, None, None, 'measured', src('no_lung', U['no'], 'Fra henvisning mottatt til første fremmøte utredende avdeling                                                  7 kalenderdager', 2026)),
            'first_visit_to_decision': P(21, None, None, 'measured', src('no_lung', U['no'], 'Fra første fremmøte i utredende avdeling til avsluttet utredning (beslutning tas)                              21 kalenderdager', 2026)),
            'decision_to_treatment': P(14, 7, 14, 'measured', src('no_lung', U['no'], 'Fra avsluttet utredning til start behandling                                        Medikamentell behandling   7 kalenderdager', 2026), note='surgery 14, drug 7, radiotherapy 14'),
            'referral_to_treatment': P(42, 35, 42, 'measured', src('no_lung', U['no'], 'Fra henvisning mottatt til start behandling                                         Medikamentell behandling   35 kalenderdager', 2026), note='surgery 42, drug 35, radiotherapy 42; page last revised 3 July 2026'),
        },
        'SE_svf_lung': {
            'suspicion_to_treatment': P(44, 40, 44, 'measured', src('se_svf', U['se'], 'Start av första behandling, kirurgi eller strålbehandling | 44 kalenderdagar', 2024),
                                        note='From decision of well-founded suspicion: drug 40, surgery/radiotherapy 44, palliative symptom relief 30 calendar days; target 80 % of patients within lead time. Version 1.4, 2024-11-05.'),
            'achieved': src('svf', U['svf'], 'Lung cancer                            30–44                30', 2023,
                            claim='In one Swedish region in 2018 only 30 % of lung cancer pathway patients started treatment within the lead time (30-44 days); 72 % of lung cancer patients were diagnosed via the pathway.', design='registry cohort, state transition model', n=19204),
        },
        'DK_kraeftpakke_lung': {
            'referral_to_first_visit': P(6, None, None, 'measured', src('dk_lung2', U['dk'], 'Fra henvisning modtaget til første fremmøde på                        6 kalenderdage', 2016)),
            'first_visit_to_end_of_workup': P(24, None, None, 'measured', src('dk_lung2', U['dk'], 'Fra første fremmøde på udredende afdeling til                         24 kalenderdage', 2016)),
            'workup_to_treatment': P(14, 11, 15, 'measured', src('dk_lung2', U['dk'], 'Stråleterapi   15 kalenderdage', 2016), note='surgery 14, radiotherapy 15, chemotherapy 11'),
            'referral_to_treatment': P(44, 41, 45, 'measured', src('dk_lung2', U['dk'], 'Kemoterapi     41 kalenderdage', 2016),
                                       note='surgery 44, radiotherapy 45, chemotherapy 41. Opened copy is the 2016 Sundhedsstyrelsen pathway description (mirror). The current sst.dk PDF (' + U['dk_new'] + ') returned HTTP 429; a search summary indicates the same 6/24/14/44 values but that was not opened.'),
        },
    },
    'delay_mortality': {
        'hr_per_4_weeks': {
            'surgery': P(1.06, 1.06, 1.08, 'measured', src('hanna', U['hanna'], 'all indications showing a hazard ratio for each four week delay of between 1.06 and 1.08 (6-8% increased chance of death for each four week delay in treatment)', 2020),
                         note='range across surgical indications; e.g. colectomy 1.06 (1.01-1.12), breast surgery 1.08 (1.03-1.13)'),
            'lung_surgery': P(1.06, 0.93, 1.19, 'measured', src('hanna', U['hanna'], 'The results for lung surgery were consistent with other sites, though not statistically significant (1.06, 0.93 to 1.19).', 2020),
                              note='Only lung-specific estimate with high-validity data. Not statistically significant. Use as the model default with its full interval.'),
            'systemic': P(None, 1.01, 1.28, 'measured', src('hanna', U['hanna'], 'Estimates for systemic treatment varied (hazard ratio range 1.01-1.28).', 2020), note='range across indications, no pooled value; none lung-specific'),
            'radiotherapy_head_neck': P(1.09, 1.05, 1.14, 'measured', src('hanna', U['hanna'], 'Radiotherapy estimates were for radical radiotherapy for head and neck cancer (hazard ratio 1.09, 95% confidence interval 1.05 to 1.14)', 2020)),
            'lung_chemoradiation': P(None, None, None, 'measured', src('hanna', U['hanna'], 'NSCLC, stage III chemoradiation No high validity data found SCLC, limited stage chemoradiation No high validity data found', 2020), note='No high-validity data for lung chemoradiation.'),
        },
        'design': 'systematic review and meta-analysis, 34 studies, 17 indications, n=1 272 681',
        'caveat_en': 'Delay in Hanna et al. is diagnosis -> first treatment (curative, neoadjuvant, adjuvant). It does not cover the patient or primary care intervals. Applying it to pre-diagnosis days is an assumption of the model.',
    },
    'finland_lung_facts': {
        'curative_intent_share_pct': P(27, None, None, 'measured', src('syopajarjestot', U['syopaj'], 'Parantavaan hoitoon ohjautui runsas neljännes (27 %) potilaista.', 2026), period='2019-2023'),
        'operated_share_pct': P(11.8, None, None, 'measured', src('paappanen', U['paappanen'], 'A recent Finnish Cancer Registry publication reported that only 11.8% of patients underwent surgery.', 2025),
                                note='Comparison in the same paper: 26.6 % in Norway, 26.0 % in Denmark.'),
        'stage_missing_share': P(None, None, None, 'measured', src('syopajarjestot', U['syopaj'], 'Levinneisyystieto puuttui lähes puolelta potilaista, mikä kertoo puutteista kliinisten syöpäilmoitusten kirjaamisessa.', 2026), note='"nearly half"; no exact percentage in the release', period='2019-2023'),
        'histology_unspecified_share': P(None, None, None, 'measured', src('laakarilehti', U['laakarilehti'], 'noin viidenneksellä potilaista syövän tarkkaa solutyyppiä ei ollut määritelty', 2026), note='"about one fifth"'),
        'stage_iv_share_pct': P(59, None, None, 'measured', src('ihe_pdf', U['ihe'], 'diagnosed with stage IV lung cancer (59%) had not changed over time. This was stated to be one of the main', 2026), note='single-centre Finnish study 2007-2019 as cited by IHE; not national'),
        'five_year_survival_pct': {
            'FI_men': P(16.7, None, None, 'measured', src('paappanen', U['paappanen'], 'The 5-year survival rate for male patients with LC between 2018 and 2022 was 16.7% in Finland, compared to 26.8% in Sweden, 28.2% in Norway, 26.2% in Denmark, and 28.4% in Iceland', 2025), period='2018-2022', note='NORDCAN as cited by Paappanen; FI women 27.3 %'),
        },
        'operability': src('paappanen', U['paappanen'], 'Among potentially operable patients, 50.6% were deemed ineligible for surgery due to various factors, including poor pulmonary or cardiac function, comorbidities, or localised tumour spread.', 2025,
                           claim='In five Finnish hospitals, half of potentially operable stage I-IIIA NSCLC patients were not operated, mostly for fitness/comorbidity reasons, not delay.', design='retrospective five-hospital cohort', n=545),
        'regional': src('yle_250979', U['yle2'], 'Syöpärekisterin mukaan Itä- ja Pohjois-Suomessa keuhkosyöpäpotilailla parantava hoito toteutuu harvemmin kuin muualla Suomessa.', 2026, claim='Curative treatment is delivered less often in Eastern and Northern Finland.'),
        'annual_new_cases': P(None, None, None, 'measured', src(None, U['fcr'], None, None, verified=False, access='blocked_403', note='Cancer Registry lung report returned 403. Take lung incidence and deaths from data/processed/indicators.jsonl (data agent, Statistics Finland / Cancer Registry API).')),
        'annual_deaths': P(None, None, None, 'measured', src(None, U['fcr'], None, None, verified=False, access='blocked_403', note='See annual_new_cases. IHE 2026 states only that lung cancer caused the most cancer deaths in both sexes in 2023 (all-cancer deaths 13,645).')),
        'all_cancer_deaths_2023': P(13645, None, None, 'measured', src('ihe_pdf', U['ihe'], 'The number of cancer deaths (mortality) in Finland was 13,645 (7,364 men and 6,281 women) in 2023 (7). Lung cancer', 2026)),
    },
    'stage_survival_5y_pct': {
        'country': 'Norway', 'period': '2020-2024', 'measure': 'five-year relative survival, lung cancer',
        'stage_I': P(71, None, None, 'measured', src('ihe_pdf', U['ihe'], 'five-year relative survival rate in stage I lung cancer was 71% compared to only 9% in stage IV in Norway in 2020-', 2026), note='secondary citation: IHE 2026 citing the Norwegian lung cancer quality registry annual report 2024'),
        'stage_IV': P(9, None, None, 'measured', src('ihe_pdf', U['ihe'], 'five-year relative survival rate in stage I lung cancer was 71% compared to only 9% in stage IV in Norway in 2020-', 2026)),
        'stage_II': P(None, None, None, 'measured', src(None, None, None, None, verified=False, note='not found in an opened source')),
        'stage_III': P(None, None, None, 'measured', src(None, None, None, None, verified=False, note='not found in an opened source')),
    },
    'inequality': {
        'education_stage_iv_or': {
            'men': P(1.10, 1.08, 1.12, 'measured', src('zai', U['zai'], 'Patients with lower education had higher odds of being diagnosed with stage IV cancer than patients with higher education (men: OR 1.10, 95% CI 1.08 to 1.12; women: OR 1.15, 95% CI 1.13 to 1.17).', 2025)),
            'women': P(1.15, 1.13, 1.17, 'measured', src('zai', U['zai'], 'Patients with lower education had higher odds of being diagnosed with stage IV cancer than patients with higher education (men: OR 1.10, 95% CI 1.08 to 1.12; women: OR 1.15, 95% CI 1.13 to 1.17).', 2025)),
            'note': 'All cancers combined, Finland 2000-2019, register-based, n = 469 522 new cancers. Lung-specific estimates are in the full paper tables and were not extracted.',
        },
        'education_mortality_hr': {
            'men': P(1.13, 1.10, 1.16, 'measured', src('zai', U['zai'], 'patients with lower education had higher mortality rates than patients with higher education (men: HR 1.13, 95% CI 1.10 to 1.16; women: HR 1.14, 95% CI 1.11 to 1.17)', 2025)),
            'women': P(1.14, 1.11, 1.17, 'measured', src('zai', U['zai'], 'patients with lower education had higher mortality rates than patients with higher education (men: HR 1.13, 95% CI 1.10 to 1.16; women: HR 1.14, 95% CI 1.11 to 1.17)', 2025)),
        },
        'distance_over_50km_mortality_hr': P(1.47, 1.07, 2.01, 'measured', src('ostrobothnia', U['ostro'], 'the adjusted HR increased to 1.47 (95% CI: 1.07–2.01; p = 0.017) for patients living in rural areas compared to those in urban areas', 2024),
                                             note='NSCLC patients first treated at Vaasa Central Hospital 2016-2020, n=321 (104 living >50 km away); 12-month survival; adjusted for performance status, frailty, stage. Single hospital, association only.'),
    },
    'curative_access': {
        'note': 'v3. Used to turn "extra patients treated with curative intent" into deaths avoided. The conversion is an assumption, not a causal estimate; the sources below are context for its size.',
        'deaths_avoided_per_extra_curative_patient': dict(
            value=0.15, lo=0.05, hi=0.30, kind='assumption',
            definition='deaths within five years avoided per additional patient who gets curative-intent treatment instead of none or non-curative treatment',
            basis='The patients a county adds at the margin are older and less fit than those already treated, and some would have been cured anyway by later treatment, so the full difference between treated and untreated groups must not be used. Context: stereotactic radiotherapy in medically inoperable stage I patients gave 40 % five-year survival (RTOG 0236) against 6 % in untreated stage I patients (population registry, not a comparison of like with like): a difference of 0.34. We count under half of that (0.15) and allow 0.05-0.30. Not adjusted for anything; observational sources.',
            context=[
                src('rtog0236', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC6117101/', 'Disease-free survival and overall survival at 5 years was 25.5% (95% CI, 14.9%-37.4%) and 40.0% (95% CI, 27.1%-52.5%), respectively', 2018, claim='Stereotactic radiotherapy for medically inoperable stage I NSCLC: 40 % alive at five years.', design='single-arm phase 2 trial, 55 evaluable patients'),
                src('raz_untreated', 'https://europepmc.org/article/MED/17505036', 'Five-year OS for untreated stage I NSCLC was 6% overall', 2007, access='abstract', claim='Untreated stage I NSCLC: 6 % alive at five years.', design='population registry, California, 1 432 untreated patients'),
                src('riaz_resection', 'https://europepmc.org/article/MED/21871792', 'A high frequency of resection was strongly inversely associated with overall mortality (HR 0.88, 95% CI 0.86-0.91 for the highest compared to the lowest resection quintile)', 2012, access='abstract', claim='English areas that operate more have lower mortality among all lung cancer patients (ecological).', design='population-based, England 2004-2006, 77 349 patients'),
                src('khakwani_nlca', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3798968/', 'increasing surgical resection rates appeared to explain some of this improvement', 2013, claim='Rising resection rates explained part of the survival improvement in England.', design='national audit cohort'),
            ]),
    },
    'screening': {
        'note': 'v3. Screening benefit = people screened x their lung cancer death rate without screening x trial effect. Cost and benefit refer to the same people.',
        'baseline_lung_deaths_per_1000_person_years': P(3.30, 2.5, 4.1, 'measured', src('nelson', U['nelson'], 'lung-cancer mortality was 2.50 deaths per 1000 person-years and 3.30 deaths per 1000 person-years, respectively', 2020, access='abstract'),
                                                         note='Control arm of NELSON (men aged 50-74, heavy smokers). lo/hi = +-25 %, our assumption, because the Finnish eligible group is not the trial population.'),
        'participants_per_100k_residents': {'value': 1000, 'lo': 600, 'hi': 1400, 'kind': 'assumption', 'basis': '2 000 eligible per 100 000 residents x 50 % take part. Same assumption as the cost. The Finnish pilot 2026-2028 will give real numbers.'},
    },
    'cost_assumptions': {
        'note': 'Unit costs used in interventions.json. All are assumptions set by us and editable; the THL unit cost page (' + U['thl_unit'] + ') returned 403 and could not be opened.',
        'nurse_fte_eur_per_year': {'value': 60000, 'kind': 'assumption', 'basis': 'registered nurse / coordinator, salary plus employer costs'},
        'specialist_physician_fte_eur_per_year': {'value': 150000, 'kind': 'assumption', 'basis': 'pulmonologist / radiologist / oncologist, salary plus employer costs'},
        'gp_fte_eur_per_year': {'value': 130000, 'kind': 'assumption', 'basis': 'health centre physician, salary plus employer costs'},
        'ct_scan_eur': {'value': 200, 'kind': 'assumption', 'basis': 'chest CT including report, public provider internal price'},
        'gp_short_visit_eur': {'value': 125, 'kind': 'assumption', 'basis': 'THL unit cost 2024 for a 1-20 min primary care doctor appointment as shown in a search-result snippet; the THL page itself could not be opened', 'url': U['thl_unit'], 'verified': False},
        'finland_population': {'value': 5600000, 'kind': 'assumption', 'basis': 'round figure used only to turn national roadmap budgets into per-100k amounts; replace with pop_total from indicators.jsonl'},
    },
}

# ---------------------------------------------------------------- interventions
def ev(slug, url, claim, quote, year, design, n, verified=True, access='full_text'):
    e = dict(claim=claim, quote=quote, url=url, year=year, design=design, n=n, verified=verified, access=access, fetched_at=FETCHED)
    if verified:
        CHECKS.append((slug, quote))
    return e


def cost(setup, per_year, scales, basis, kind='assumption', source_url=None):
    return dict(eur_setup=setup, eur_per_year=per_year, scales_with=scales, basis=basis, source_url=source_url, kind=kind)


def eff(metric, value, lo, hi, kind, basis, **kw):
    d = dict(metric=metric, value=value, lo=lo, hi=hi, kind=kind, basis=basis)
    d.update(kw)
    return d


EV_KHALIFE_CT = ev('khalife', U['khalife'], 'Finland has the lowest access to CT from primary care and the longest primary care waits in the Nordics.',
                   'Finland has the lowest access to computed tomography (CT) from primary care, longest waiting times in primary care, and lacks a national outcome tracking system.', 2025, 'survey + expert workshops', None)

interventions = [
    dict(
        id='cpp_pathway', name_en='Standardised lung cancer pathway with booked slots', name_fi='Keuhkosyövän standardoitu hoitopolku ja varatut tutkimusajat',
        step='diagnosis',
        what_en='A lung cancer pathway on the Danish/Swedish/Norwegian model: fixed referral criteria, pre-booked CT, PET-CT, bronchoscopy and MDT slots, a named pathway owner, and published time limits for each step.',
        what_fi='Tanskan, Ruotsin ja Norjan mallin mukainen hoitopolku: yhtenäiset lähetekriteerit, etukäteen varatut TT-, PET-TT-, bronkoskopia- ja MDT-ajat, nimetty vastuuhenkilö ja julkiset tavoiteajat joka vaiheelle.',
        effect=eff('days', 14, 5, 23, 'assumption',
                   'Gap between the Finnish specialist-care interval (58 days, Yle MOT 2026) and the Nordic standard times referral -> treatment: Denmark 44 (41-45), Sweden 44 (40-44), Norway 42 (35-42). value = 58-44; hi = 58-35; lo = assumption that only a third of the gap closes, because in Sweden only 30 % of lung pathway patients met the lead time. No opened study reports days saved by a pathway for lung cancer.',
                   applies_to_steps=['referral', 'diagnosis', 'treatment'],
                   secondary={'metric': 'mortality_rr', 'value': 0.74, 'lo': 0.66, 'hi': 0.83, 'basis': 'inverse of excess hazard ratio 3 years, before vs after pathway implementation = 1.35 (1.21-1.51), all seven cancers combined, Denmark; before-after design, lead-time and selection bias possible'}),
        evidence=[
            ev('jensen', U['jensen'], 'Three-year relative survival for symptomatic cancer patients diagnosed via primary care rose from 45 % to 54 % after Danish cancer patient pathways were introduced.',
               'For all cancers combined, the RS3years rose from 45% (95% confidence interval (CI): 42;47) before to 54% (95% CI: 52;56) after CPP implementation. The excess mortality was higher before than after CPP implementation (EHR3years before vs. after CPP = 1.35 (95% CI: 1.21;1.51)).', 2017, 'before-during-after cohort, Denmark', 7725),
            ev('svf', U['svf'], 'Sweden: 72 % of lung cancer patients were diagnosed through the pathway.', 'Lung cancer                                     740                  733                               525 (72%)', 2023, 'registry cohort, one Swedish region, 2018', 19204),
            ev('ihe', 'https://ihe.se/en/new-cancer-dashboard-for-finland/', 'Finland is the only Nordic country without national standardised care pathways.', 'Finland is also the only Nordic country without transparent national cancer care guidelines and standardized care pathways.', 2026, 'policy report summary (IHE)', None),
        ],
        null_results=[
            dict(claim='Sweden: only 30 % of lung cancer pathway patients started treatment within the 30-44 day lead time; a pathway on paper does not deliver the time by itself.', url=U['svf'], year=2023),
            dict(claim='Danish authors note the survival gain may partly reflect lead-time bias and selection bias.', url=U['jensen'], year=2017),
        ],
        cost=cost(50000, 90000, 'county', 'Setup: process design and booking templates, 50 000 EUR. Yearly: 1.0 pathway coordinator nurse (60 000) + 0.2 pulmonologist as pathway owner (0.2 x 150 000 = 30 000). Booked slots reallocate existing capacity. National guideline and pathway work is budgeted separately in the roadmap: 5 000 000 EUR/year (measure 3.1.1, covers 2.5.2, 3.1.2-3.1.4).'),
        roadmap_measure='3.1.2', roadmap_measures_related=['2.5.2', '3.1.1', '3.1.4'],
        owner_fi='Keuhkosairauksien ylilääkäri (alueellinen polku); FICAN ja kansallinen keuhkosyöpäryhmä (kansallinen hoitoketjukuvaus)', owner_en='Chief physician of pulmonology (county pathway); FICAN and the national lung cancer group (national pathway description)',
        prerequisite_en='Imaging and bronchoscopy slots must actually exist; needs time stamps recorded per step so the limits can be monitored.', confidence='medium'),
    dict(
        id='same_day_cxr_ct', name_en='Same-day chest X-ray report with immediate CT', name_fi='Thorax-kuvan lausunto samana päivänä ja välitön TT',
        step='primary',
        what_en='A radiologist or reporting radiographer reads primary-care chest X-rays while the patient waits; if suspicious, CT is done the same day or within days and the referral is triggered by radiology.',
        what_fi='Radiologi lausuu perusterveydenhuollon thorax-kuvan potilaan odottaessa; epäilyttävä löydös johtaa TT-kuvaukseen samana päivänä tai lähipäivinä ja lähete käynnistyy radiologiasta.',
        effect=eff('days', 31, 0, 46, 'measured', 'Median chest X-ray -> lung cancer diagnosis 32 days (IQR 19-70) with immediate reporting vs 63 days (IQR 29-78) with standard reporting, p=0.03. No confidence interval reported: lo = 0 (small trial, 49 cancers), hi = assumption. The interval measured spans our steps primary, referral and diagnosis; the model should cap the saving at the days available in those steps.',
                   applies_to_steps=['primary', 'referral', 'diagnosis']),
        evidence=[
            ev('radiox', U['radiox'], 'Immediate reporting of primary-care chest X-rays halved time to lung cancer diagnosis.',
               'The median time from CXR to diagnosis of lung cancer for IR was 32 days (IQR 19, 70) compared with 63 days (IQR 29, 78) for SR (p=0.03).', 2023, 'randomised controlled trial (radioX), single London hospital', 8682),
            ev('yle_mot', U['yle_mot'], 'Finnish specialist care loses time waiting for imaging and reports.', 'Erikoissairaanhoidossa on taas odottamista esimerkiksi kuvaukseen, kuvauslausuntoon ja näytteenottoon.', 2026, 'journalism citing unpublished four-city study', None),
        ],
        null_results=[dict(claim='In the same trial, mean days to diagnosis did not differ (54.4 vs 50.3); the effect is on the median and rests on 49 cancers.', url=U['radiox'], year=2023)],
        cost=cost(20000, 105000, 'county', 'Setup: workflow and referral-rule change, 20 000 EUR. Yearly: 0.5 radiologist for hot reporting (0.5 x 150 000 = 75 000) + 0.5 radiographer/coordinator (30 000). CT volume is brought forward, not added.'),
        roadmap_measure='2.5.2', roadmap_measures_related=['3.1.2'],
        owner_fi='Kuvantamisen ylilääkäri yhdessä perusterveydenhuollon johtavan lääkärin kanssa', owner_en='Chief radiologist together with the chief physician of primary care',
        prerequisite_en='CT capacity for same-week scans; radiology allowed to trigger the specialist referral.', confidence='medium'),
    dict(
        id='gp_direct_ct', name_en='GP direct access to low-dose CT', name_fi='Yleislääkärin suora lähete matala-annos-TT:hen',
        step='primary',
        what_en='Health-centre doctors can order chest CT directly for patients whose symptoms raise suspicion but do not meet urgent referral criteria, without first referring to specialist care.',
        what_fi='Terveyskeskuslääkäri voi tilata keuhkojen TT-kuvauksen suoraan, kun oireet herättävät epäilyn mutta kiireellisen lähetteen kriteerit eivät täyty.',
        effect=eff('days', 8, 0, 16, 'measured', 'Median diagnostic interval 36 days (intervention GPs) vs 44 days (control GPs), p=0.299, not statistically significant. value = 44-36; lo = 0 because the trial is null; hi = assumption (twice the point estimate).',
                   applies_to_steps=['primary', 'referral']),
        evidence=[
            ev('gpct', U['gpct'], 'Danish cluster-randomised trial: direct CT access gave a non-significant 8-day shorter diagnostic interval and no stage shift.',
               'Patients listed with control GPs had a statistically insignificantly longer median diagnostic interval (44 days, IQI: 17–112) than patients listed with intervention GPs (36 days, IQI: 17–83) ( p = 0.299).', 2015, 'cluster-randomised controlled trial, Aarhus, 119 practices', 331),
            EV_KHALIFE_CT,
            ev('yle_mot', U['yle_mot'], 'The lead investigator of the Finnish delay study recommends direct CT ordering from primary care.',
               'Kuittisen mielestä heidän pitäisi myös saada määrätä suoraan tietokonekuvauksia sen sijaan, että potilas joutuu siirtymään erikoissairaanhoidon puolelle jonottamaan kuvauksia.', 2026, 'expert opinion', None),
        ],
        null_results=[dict(claim='Direct low-dose CT from primary care did not statistically significantly decrease time to diagnosis or change stage at diagnosis.', url=U['gpct'], year=2015)],
        cost=cost(10000, 60000, 'per_100k_pop', 'Setup: one training round for GPs, 10 000 EUR. Yearly per 100 000 residents: about 300 extra CT scans x 200 EUR = 60 000 EUR. The number of scans is an assumption.'),
        roadmap_measure='2.5.2', roadmap_measures_related=['2.5.1'],
        owner_fi='Perusterveydenhuollon johtava lääkäri ja kuvantamisen ylilääkäri', owner_en='Chief physician of primary care and chief radiologist',
        prerequisite_en='Baseline matters: Denmark already had fast-track referral; Finland starts from the lowest primary-care CT access in the Nordics, so the Danish null result may understate the Finnish effect. That is a hypothesis, not evidence.', confidence='low'),
    dict(
        id='ai_cxr_triage_alone', name_en='AI chest X-ray triage without added capacity', name_fi='Tekoäly thorax-kuvien priorisoinnissa ilman lisäkapasiteettia',
        step='primary',
        what_en='AI software flags suspicious primary-care chest X-rays so they are reported first. Included as a documented null result: the tool should not recommend it alone.',
        what_fi='Tekoäly nostaa epäilyttävät thorax-kuvat lausuntojonon kärkeen. Mukana dokumentoituna nollatuloksena: työkalu ei suosittele tätä yksinään.',
        effect=eff('relative_days', 0.02, -0.16, 0.17, 'measured', 'Ratio of geometric means for time to lung cancer diagnosis 0.98 (95 % CI 0.83-1.16), i.e. 2 % shorter, compatible with no effect. Medians 44 vs 46 days. Time to treatment 76 vs 72.5 days.'),
        evidence=[
            ev('lungimpact', U['lungimpact'], 'Randomised trial of 93 326 chest X-rays: AI prioritisation changed neither time to CT nor time to diagnosis.',
               'Median times to diagnosis were 44 days (26–90) and 46 days (24–105) respectively, with a ratio of geometric means of 0.98 (95% CI = 0.83–1.16; P = 0.84).', 2026, 'prospective multicentre randomised controlled trial (LungIMPACT), UK', 93326),
            ev('lungimpact', U['lungimpact'], 'Authors conclude AI worklist prioritisation should not be deployed for this purpose.',
               'AI prioritization of CXR requested by UK primary care has no significant impact on the lung cancer pathway. Therefore, CXR AI deployments should not include worklist prioritization in this context.', 2026, 'randomised controlled trial', 93326),
        ],
        null_results=[
            dict(claim='Time to CT 53 vs 53 days; ratio of geometric means 0.97 (0.93-1.02), P=0.31.', url=U['lungimpact'], year=2026),
            dict(claim='No difference in time to referral (14 vs 15 days), time to treatment (76 vs 72.5 days) or stage at diagnosis (P=0.34).', url=U['lungimpact'], year=2026),
        ],
        cost=cost(50000, 100000, 'county', 'Setup: integration with PACS/RIS, 50 000 EUR. Yearly licence 100 000 EUR per county. Both are assumptions; no Finnish price was found. Nationally the roadmap budgets 1 140 000 EUR for digital pathways and AI tools (measure 3.5.3).'),
        roadmap_measure='3.5.3', roadmap_measures_related=[],
        owner_fi='Kuvantamisen ylilääkäri; FICAN (kansallinen tekoälyratkaisujen selvitys)', owner_en='Chief radiologist; FICAN (national review of AI tools)',
        prerequisite_en='Only worth buying together with reporting and CT capacity that can act on the flag (see same_day_cxr_ct).', confidence='high'),
    dict(
        id='ebus_capacity', name_en='EBUS as first test, with enough bronchoscopy capacity', name_fi='EBUS ensimmäisenä tutkimuksena ja riittävä bronkoskopiakapasiteetti',
        step='diagnosis',
        what_en='Endobronchial ultrasound-guided needle biopsy as the first invasive test after CT for suspected stage I-IIIA disease, giving diagnosis and staging in one procedure, with enough EBUS lists (own or bought) to do it within a week.',
        what_fi='Kaikututkimusohjattu bronkoskopianäyte (EBUS) ensimmäisenä kajoavana tutkimuksena TT:n jälkeen, jolloin diagnoosi ja levinneisyys saadaan samalla kertaa; riittävästi EBUS-aikoja (omana työnä tai ostopalveluna) viikon sisään.',
        effect=eff('days', 15, 8, 21, 'measured', 'Median time to treatment decision 14 days (95 % CI 14-15) with EBUS first vs 29 days (95 % CI 23-35) with conventional work-up. value = 29-14; lo/hi from the two confidence intervals (23-15, 35-14). Applies to patients with suspected stage I-IIIA disease.',
                   applies_to_share_note='suspected stage I-IIIA only'),
        evidence=[
            ev('lungboost', U['lungboost'], 'Randomised trial: EBUS as initial investigation halved time to treatment decision.',
               'The median time to treatment decision was shorter with EBUS-TBNA (14 days; 95% CI 14-15) than with CDS (29 days; 23-35) resulting in a hazard ratio of 1·98', 2015, 'open-label multicentre randomised controlled trial (Lung-BOOST), six UK centres', 133),
            ev('thl_b1', U['thl'], 'Finnish target: tissue sample within a week of the request.', 'biopsia tai neulanäyte) tulee ottaa viikon kuluessa tutkimuspyynnön saapumisesta kirurgiseen yksikköön tai', 2016, 'national guidance (THL Ohjaus 21/2016)', None),
        ],
        null_results=[],
        cost=cost(150000, 75000, 'county', 'Setup: one EBUS scope and processor, 150 000 EUR (zero if the hospital already has one). Yearly: 0.3 pulmonologist (45 000) + 0.5 endoscopy nurse (30 000) for one extra weekly list. Alternative: buy the procedures from the university hospital.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.1'],
        owner_fi='Keuhkosairauksien ylilääkäri', owner_en='Chief physician of pulmonology',
        prerequisite_en='Trained EBUS operators and on-site cytology; pathology must turn the sample around within a week.', confidence='high'),
    dict(
        id='reflex_molecular', name_en='Reflex molecular testing ordered by pathology', name_fi='Patologian käynnistämä refleksitestaus (molekyylidiagnostiikka)',
        step='diagnosis',
        what_en='The pathologist starts the biomarker panel (EGFR, ALK, ROS1, PD-L1, NGS) as soon as non-small cell lung cancer is seen, without waiting for the oncologist to order it. The result now decides treatment at every stage: osimertinib or alectinib after surgery, durvalumab or osimertinib after chemoradiotherapy in stage III, and the first drug in advanced disease.',
        what_fi='Patologi käynnistää biomarkkeripaneelin (EGFR, ALK, ROS1, PD-L1, NGS) heti ei-pienisoluisen keuhkosyövän toteamisen jälkeen odottamatta onkologin tilausta. Tulos ohjaa nykyisin hoitoa kaikissa levinneisyysasteissa: liitännäishoito leikkauksen jälkeen, kemosädehoidon jälkeinen hoito asteessa III ja ensilinjan lääke levinneessä taudissa.',
        effect=eff('days', 7, 0, 14, 'assumption', 'Measured in one US centre: mean time to initiation of molecular testing fell from 27.4 weekdays (in-house, clinician-ordered) to 0.95 weekdays (reflex); reporting time unchanged at about 11 weekdays. The Finnish ordering delay is not published, so we assume 0-14 calendar days are removable for the patients whose first treatment waits for the result. Biomarkers now gate treatment in resected stage IB-IIIA (ADAURA, ALINA), unresectable stage III (PACIFIC, LAURA) and advanced disease. The model counts deaths avoided only through earlier curative-intent treatment; the benefit of earlier targeted drugs in advanced disease is real and not counted.',
                   measured_effect={'metric': 'weekdays_to_test_initiation', 'before': 27.4, 'after': 0.95}, applies_to_share_note='non-small cell lung cancer at any stage where the first treatment decision needs the result'),
        evidence=[
            ev('adaura', 'https://europepmc.org/article/MED/32955177', 'Resected EGFR-mutated NSCLC: 89 % vs 52 % alive and disease-free at 24 months with adjuvant osimertinib, so EGFR status is needed after surgery.',
               'In the overall population, 89% of the patients in the osimertinib group (95% CI, 85 to 92) and 52% of those in the placebo group (95% CI, 46 to 58) were alive and disease-free at 24 months', 2020, 'randomised controlled trial (ADAURA)', 682, access='abstract'),
            ev('alina', 'https://europepmc.org/article/MED/38598794', 'Resected ALK-positive NSCLC: 93.8 % vs 63.0 % alive and disease-free at 2 years with adjuvant alectinib.',
               'The percentage of patients alive and disease-free at 2 years was 93.8% in the alectinib group and 63.0% in the chemotherapy group among patients with stage II or IIIA disease', 2024, 'randomised controlled trial (ALINA)', 257, access='abstract'),
            ev('laura', 'https://europepmc.org/article/MED/38828946', 'Stage III EGFR-mutated NSCLC after chemoradiotherapy: median progression-free survival 39.1 vs 5.6 months with osimertinib.',
               'the median progression-free survival was 39.1 months with osimertinib versus 5.6 months with placebo', 2024, 'randomised controlled trial (LAURA)', 216, access='abstract'),
            ev('pacific', 'https://europepmc.org/article/MED/28885881', 'Stage III NSCLC after chemoradiotherapy: durvalumab lengthened progression-free survival, so PD-L1 and EGFR status are needed before consolidation.',
               'The median progression-free survival from randomization was 16.8 months (95% confidence interval [CI], 13.0 to 18.1) with durvalumab versus 5.6 months', 2017, 'randomised controlled trial (PACIFIC)', 713, access='abstract'),
            ev('reflex', U['reflex'], 'Reflex protocol cut time to initiation of molecular testing from about 27 weekdays to under 1.',
               'IT was lowest for reflex protocol orders (mean weekdays: 30.0 send-out, 27.4 in-house clinician-ordered, 0.95 reflex).', 2023, 'retrospective review of three workflows, single US institution', 578, access='abstract'),
            ev('reflex', U['reflex'], 'Reflex testing also reduced care given without biomarker information.',
               'with a reduction in nonbiomarker informed care (58.8% send-out, 19.5% in-house clinician-ordered, 11.5% reflex)', 2023, 'retrospective review', 578, access='abstract'),
            ev('ihe', 'https://ihe.se/en/new-cancer-dashboard-for-finland/', 'IHE lists suboptimal use of advanced biomarker testing among Finnish gaps.', 'It has also comparatively long waiting times to get a confirmed diagnosis, suboptimal use of advanced biomarker testing', 2026, 'policy report summary (IHE)', None),
        ],
        null_results=[dict(claim='Reporting time itself did not change (11.1, 11.9, 11.4 weekdays); the gain is only in when the test starts.', url=U['reflex'], year=2023)],
        cost=cost(20000, 150, 'per_patient', 'Setup: protocol and laboratory information system rule, 20 000 EUR. Per newly diagnosed NSCLC patient per year: about 150 EUR, assuming 10-15 % more panels run at roughly 1 000-1 500 EUR each. Panel price is an assumption.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.1'],
        owner_fi='Patologian ylilääkäri yhdessä syöpätautien ylilääkärin kanssa', owner_en='Chief pathologist together with the chief physician of oncology',
        prerequisite_en='Agreed national testing panel; molecular pathology capacity (roadmap 3.5.1 names molecular diagnostics staffing as a need).', confidence='medium'),
    dict(
        id='liquid_biopsy_first', name_en='Plasma ctDNA test before tissue diagnosis', name_fi='Plasman ctDNA-testi ennen kudosdiagnoosia',
        step='diagnosis',
        what_en='For patients whose imaging already shows advanced lung cancer, a blood-based ctDNA genotyping test is sent at the first specialist visit, in parallel with the biopsy.',
        what_fi='Kun kuvantaminen jo viittaa levinneeseen keuhkosyöpään, verestä tehtävä ctDNA-genotyypitys lähetetään ensikäynnillä rinnakkain koepalan kanssa.',
        effect=eff('days', 23, 0, 23, 'measured', 'Median referral -> treatment 39 days (IQR 27-52) vs 62 days (IQR 44-82) in a reference cohort; non-randomised. value = 62-39; lo = 0 because of the design. Applies only to advanced non-squamous NSCLC (60 % of enrolled patients in the trial).',
                   applies_to_steps=['diagnosis', 'treatment'], applies_to_share_note='advanced non-squamous NSCLC only'),
        evidence=[
            ev('accelerate', U['accelerate'], 'Plasma-first genotyping was associated with 23 days shorter time to treatment.',
               'The median time to treatment was 39 days (IQR, 27-52 days) for the ACCELERATE cohort vs 62 days (IQR, 44-82 days) for the reference cohort', 2023, 'single-group non-randomised trial with reference cohort, Toronto', 150),
        ],
        null_results=[dict(claim='Single-centre, non-randomised; reference cohort is historical standard care, so part of the difference may be confounded.', url=U['accelerate'], year=2023)],
        cost=cost(10000, 2000, 'per_patient', 'Setup: logistics and ordering, 10 000 EUR. About 2 000 EUR per tested patient (commercial ctDNA NGS assay); price is an assumption, no Finnish list price was opened.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.3'],
        owner_fi='Syöpätautien ylilääkäri ja patologian/genetiikan laboratorio', owner_en='Chief physician of oncology and the pathology/genetics laboratory',
        prerequisite_en='Useful only where tissue genotyping is the bottleneck; needs a validated assay and a rule for acting on a plasma result.', confidence='low'),
    dict(
        id='nurse_navigator', name_en='Nurse navigator for every suspected lung cancer', name_fi='Hoitajakoordinaattori jokaiselle keuhkosyöpäepäilylle',
        step='treatment',
        what_en='A named nurse books and chases every test, calls the patient, prepares the MDT and removes waiting between steps from referral to first treatment.',
        what_fi='Nimetty hoitaja varaa ja varmistaa tutkimukset, pitää yhteyttä potilaaseen, valmistelee MDT-kokouksen ja poistaa odotusta vaiheiden välistä lähetteestä ensimmäiseen hoitoon.',
        effect=eff('relative_days', 0.15, 0.0, 0.30, 'assumption', 'The opened scoping review reports times achieved under navigation (diagnosis -> treatment under 60 days; abnormal imaging -> treatment 38 days) but no pooled difference versus control. 15 % (0-30 %) of the step is our assumption.',
                   applies_to_steps=['referral', 'diagnosis', 'treatment']),
        evidence=[
            ev('navigator', U['navigator'], 'Scoping review of 13 studies: navigation shortened diagnosis-to-treatment waits.',
               'CPN interventions accelerated services by reducing waiting times from diagnosis to first treatment to <60 days, including biopsy to treatment in 2 days, abnormal imaging to treatment in 38 days', 2026, 'scoping review, 13 studies, several cancers including lung', None),
        ],
        null_results=[dict(claim='No pooled effect size; included studies are mostly retrospective cohorts in other health systems.', url=U['navigator'], year=2026)],
        cost=cost(5000, 60000, 'county', 'Yearly: 1.0 nurse (60 000 EUR) per county, enough for roughly 150 new lung cancer patients a year; large counties need more. Setup: training, 5 000 EUR.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.2'],
        owner_fi='Keuhkosairauksien ja syöpätautien osastonhoitajat; ylihoitaja', owner_en='Head nurses of pulmonology and oncology; director of nursing',
        prerequisite_en='Authority to book across radiology, pulmonology, pathology and oncology calendars.', confidence='low'),
    dict(
        id='ldct_screening', name_en='Low-dose CT screening for long-term heavy smokers', name_fi='Matala-annos-TT-seulonta pitkään tupakoineille',
        step='patient',
        what_en='Invite 50-74-year-old long-term heavy smokers to low-dose CT with smoking cessation support, so cancers are found before symptoms. Finland is piloting this in 2026-2028.',
        what_fi='Kutsutaan 50–74-vuotiaat pitkään ja paljon tupakoineet matala-annos-TT-kuvaukseen ja tupakkavieroitukseen, jolloin syöpä löytyy ennen oireita. Suomessa pilotti 2026–2028.',
        effect=eff('mortality_rr', 0.84, 0.76, 0.92, 'measured', 'Pooled relative rate of lung cancer death, nine randomised trials. It applies to the people screened. Deaths avoided per year = people screened (1 000 per 100 000 residents: the same people the cost pays for) x their lung cancer death rate without screening (3.30 per 1 000 person-years, NELSON control arm) x (1 - 0.84) = 0.53 per 100 000 residents. At about 320 000 EUR a year per 100 000 residents that is roughly 600 000 EUR per death avoided.',
                   participants_per_100k=1000, baseline_deaths_per_1000_person_years=3.30, deaths_avoided_per_100k_residents=0.53),
        evidence=[
            ev('ldct_pooled', U['ldct'], 'Meta-analysis of nine randomised trials: 16 % lower lung cancer mortality with LDCT screening.',
               'The meta-analysis indicated a significant reduction in lung cancer mortality with a pooled overall relative rate of 0.84 (95% CI 0.76-0.92) from nine eligible trials.', 2021, 'randomised trial (UKLS) + random-effects meta-analysis of 9 trials', 3968),
            ev('nelson', U['nelson'], 'NELSON control arm: 3.30 lung cancer deaths per 1 000 person-years among unscreened heavy smokers (the baseline risk used here).',
               'lung-cancer mortality was 2.50 deaths per 1000 person-years and 3.30 deaths per 1000 person-years, respectively', 2020, 'randomised controlled trial, Netherlands and Belgium', 15789, access='abstract'),
            ev('nelson', U['nelson'], 'NELSON: 24 % lower lung cancer mortality in men at 10 years.',
               'The cumulative rate ratio for death from lung cancer at 10 years was 0.76 (95% confidence interval [CI], 0.61 to 0.94; P = 0.01) in the screening group as compared with the control group', 2020, 'randomised controlled trial, Netherlands and Belgium', 15789, access='abstract'),
            ev('ihe_pdf', U['ihe'], 'Finnish Oulu pilot: 5 of 6 screen-detected cancers were stage I.',
               'participants were detected. Five of the detected cases (83%) were detected in stage I, while one case was', 2026, 'pilot study (LDCT-SC-FI, Oulu, 200 participants) as cited by IHE', 200),
            ev('yle_ldct', U['yle_ldct'], 'Finnish national pilot: 1 200 long-term smokers from five regions.',
               'Pilottiin valikoidaan 1 200 pitkään tupakoinutta henkilöä Uudenmaan, Pirkanmaan, Pohjanmaan, Pohjois-Pohjanmaan ja Varsinais-Suomen alueilta.', 2026, 'news report on national pilot', 1200),
            ev(None, U['nhs'], 'NHS targeted lung health checks: about 76 % of cancers found at stage I-II.', None, 2024, 'programme statistics (NHS England press release)', None, verified=False, access='blocked'),
        ],
        null_results=[dict(claim='UKLS alone did not reach significance: relative rate 0.65 (0.41-1.02), p=0.062.', url=U['ldct'], year=2021)],
        cost=cost(100000, 300000, 'per_100k_pop', 'Per 100 000 residents per year: assume 2 000 eligible, 50 % take part -> 1 000 scans x 250 EUR (scan, reading, invitation) = 250 000; follow-up scans for about 10 % = 25 000; 0.4 coordinator nurse = 24 000; total about 300 000 EUR. Setup 100 000 EUR for invitation system and nodule protocol. Eligible numbers and prices are assumptions; the Finnish pilot 2026-2028 will give real ones. The roadmap gives no budget ("arviota ei tässä vaiheessa esitetä").'),
        roadmap_measure='2.3.4', roadmap_measures_related=['2.3.1', '2.3.2'],
        owner_fi='STM ja Palko (päätös), Suomen Syöpärekisteri (ohjaus), hyvinvointialue (toteutus)', owner_en='Ministry of Social Affairs and Health and Palko (decision), Finnish Cancer Registry (steering), county (delivery)',
        prerequisite_en='A national decision (Ministry, Palko). A county cannot start a screening programme alone, so it is never bought from a county budget. Needs smoking-history data to find eligible people, and CT and thoracic surgery capacity for the cancers found. Benefits arrive after years, not within a budget year.', confidence='high'),
    dict(
        id='symptom_campaign', name_en='Symptom awareness campaign (cough over three weeks)', name_fi='Oiretietoisuuskampanja (yli kolme viikkoa jatkunut yskä)',
        step='patient',
        what_en='A campaign on the English "Be Clear on Cancer" model telling people with a persistent cough to see a doctor. Weak evidence: in England the share found at stage I rose during the campaign months and faded within months, so it has to be repeated every year, and the extra GP visits and chest X-rays cost several times the advertising.',
        what_fi='Englannin Be Clear on Cancer -mallin mukainen kampanja, joka ohjaa pitkittyneestä yskästä kärsivät lääkäriin. Näyttö on heikko: Englannissa varhaisvaiheessa todettujen osuus nousi kampanjakuukausina ja palasi ennalleen muutamassa kuukaudessa, joten kampanja on toistettava vuosittain, ja lisäkäynnit ja keuhkokuvat maksavat moninkertaisesti mainontaan verrattuna.',
        effect=eff('stage_shift_pp', 0.8, 0.0, 1.6, 'estimated', 'Average over a year, not the campaign months. Measured: the share of NSCLC diagnosed at stage I rose by 3.1 points (14.1 % to 17.3 %) during the campaign period, and stayed higher only "for several months after the campaign (until October)". One campaign a year: 3.1 points for about 3 of 12 months = 0.8 points averaged over the year; upper bound 1.6 if the full effect lasted 6 months; lower bound 0 because it is a before-after comparison and the regional pilot did not reach significance.',
                   measured_during_campaign_pp=3.1, months_at_full_effect=3, fades=True),
        evidence=[
            ev('bcoc', U['bcoc'], 'English national lung campaign: stage I share of NSCLC +3.1 percentage points.',
               'the proportion of NSCLCs diagnosed at stage I increased by 3.1 percentage points during the campaign period, (from 14.1% to 17.3%, P &lt;0.001; a proportional increase of 22%)', 2015, 'before-after evaluation of national campaign, England', None),
            ev('yle_mot', U['yle_mot'], 'The patient interval is the longest single step in Finland.', Q_MOT_STEPS, 2026, 'journalism citing unpublished four-city study', None),
            ev('yle_mot', U['yle_mot'], 'Stated reasons for late presentation: cost and fear.',
               'syöpäjärjestöjen kyselyn mukaan moni välttelee lääkärin menoa taloudellisista syistä tai sen takia, että ajatus syövän löytämisestä pelottaa', 2026, 'survey by cancer organisations as reported by Yle', None),
            ev('bcoc', U['bcoc'], 'The stage effect faded within months of the campaign.',
               'The proportion of NSCLC cases diagnosed at stage I appeared to be higher for several months after the campaign (until October)', 2015, 'before-after evaluation of national campaign, England', None),
            ev('bcoc', U['bcoc'], 'The campaign raised GP chest X-ray requests by 20 %: the downstream workload is the main cost.',
               'a change in GP behaviour with a 20% increase in chest X-ray (CXR) requests', 2015, 'regional pilot evaluation, England', None),
        ],
        null_results=[dict(claim='Stage shift in the regional pilot did not reach significance; effect is a before-after comparison and faded some months after the campaign.', url=U['bcoc'], year=2015)],
        cost=cost(0, 69600, 'per_100k_pop', 'Per 100 000 residents per year. Advertising: 7 100 EUR (roadmap measure 1.3.2 budgets 400 000 EUR nationally; 400 000 / 5.6 million x 100 000). Extra health-care use during and after the campaign, our assumption: 300 extra GP visits x 125 EUR = 37 500; 250 extra chest X-rays x 60 EUR = 15 000; 50 extra CT scans x 200 EUR = 10 000. Total 69 600 EUR, repeated every year because the effect fades. Only the advertising figure comes from a source.', kind='assumption', source_url='res/roadmap/r.txt#L1644'),
        roadmap_measure='1.3.2', roadmap_measures_related=[],
        owner_fi='FICAN ja Syöpäjärjestöt (kansallinen kampanja); hyvinvointialueen viestintä ja perusterveydenhuolto (alueellinen toteutus)', owner_en='FICAN and the Cancer Society (national campaign); county communications and primary care (local delivery)',
        prerequisite_en='Primary care must be able to see the extra patients quickly; in England urgent referrals rose during the campaign.', confidence='low'),
    dict(
        id='nssc_rapid_dx_centre', name_en='Rapid diagnostic centre for non-specific symptoms', name_fi='Diagnostinen keskus epämääräisille syöpäoireille',
        step='primary',
        what_en='One referral route for patients with serious but non-specific symptoms (weight loss, fatigue, abnormal bloods): a small team does bloods, CT and review within days, on the Danish NSSC pathway model.',
        what_fi='Yksi lähetereitti potilaille, joilla on vakavia mutta epämääräisiä oireita (laihtuminen, väsymys, poikkeavat verikokeet): pieni tiimi tekee verikokeet, TT:n ja arvion päivien sisällä Tanskan mallin mukaan.',
        effect=eff('relative_days', 0.10, 0.0, 0.25, 'assumption', 'The opened Danish study is descriptive (8 % of 314 referrals had cancer) and gives no time comparison. 10 % (0-25 %) of the primary care interval is our assumption. The Lancet Primary Care 2025 paper named in the brief could not be opened.'),
        evidence=[
            ev('nssc', U['nssc'], 'Danish diagnostic centre: 8 % of referrals with non-specific symptoms had cancer.',
               'Of total referrals, 25 (8%) received a malignant diagnosis, 20 (6%) a non-malignant but clinically relevant diagnosis with initiation of treatment', 2024, 'prospective descriptive study, one Danish diagnostic centre', 314, access='abstract'),
            ev(None, 'https://www.thelancet.com/journals/lanprc/article/PIIS3050-5143(25)00019-6/fulltext', 'Lancet Primary Care 2025 evaluation of rapid diagnostic centres.', None, 2025, 'not opened (HTTP 403)', None, verified=False, access='blocked_403'),
        ],
        null_results=[dict(claim='81 % of referrals had no serious new condition; no evidence opened on days saved or stage shift.', url=U['nssc'], year=2024)],
        cost=cost(50000, 195000, 'county', 'Yearly: 0.5 internist/GP (75 000) + 1.0 nurse (60 000) + about 300 CT scans x 200 EUR (60 000) = 195 000 EUR. Setup 50 000 EUR.'),
        roadmap_measure='2.5.2', roadmap_measures_related=['3.1.2'],
        owner_fi='Perusterveydenhuollon johtava lääkäri ja sisätautien/yleislääketieteen ylilääkäri', owner_en='Chief physician of primary care and chief of internal/general medicine',
        prerequisite_en='Standard referral criteria (roadmap 2.5.2) and guaranteed imaging slots.', confidence='low'),
    dict(
        id='gp_capacity_econsult', name_en='Faster access to a doctor in primary care, with pulmonologist e-consultation', name_fi='Nopeampi pääsy lääkärille perusterveydenhuollossa ja keuhkolääkärin sähköinen konsultaatio',
        step='primary',
        what_en='Extra doctor capacity and continuity (personal doctor model) so a patient with lung symptoms meets a doctor within a week, plus a same-week electronic consultation line from GP to pulmonologist.',
        what_fi='Lisää lääkäriresurssia ja hoidon jatkuvuutta (omalääkärimalli), jotta keuhko-oireinen pääsee lääkärille viikossa, sekä yleislääkärin ja keuhkolääkärin välinen sähköinen konsultaatio saman viikon aikana.',
        effect=eff('days', 9, 0, 12, 'assumption', 'Survey mode for getting a health-centre appointment with lung cancer symptoms: Finland 14 days vs 2-7 days in the other Nordic countries. Closing that gap saves 7-12 days; value = midpoint, lo = 0. No trial opened; e-consultation effect not quantified.'),
        evidence=[
            ev('khalife', U['khalife'], 'Appointment wait 14 days in Finland vs 2-7 days in other Nordics.',
               'To secure an appointment at the health center for patients with LC symptoms (days)       14        2–7       2–7      2–7       2–7', 2025, 'survey of healthcare professionals + expert workshops', None),
            ev('khalife', U['khalife'], 'National data: 35 % waited over 14 days for a primary care doctor in 2023.',
               'In 2023, 35% of patients waited longer than 14 days to see a doctor in primary care, and 14% waited for 1–3 months', 2025, 'national statistics cited in paper', None),
            ev('khalife', U['khalife'], 'Only 40-60 % of Finnish patients meet a doctor at first contact.',
               'Mode of reported share of patients meeting a doctor in the first healthcare contact    40–60%    80–100%    100%      100%     100%', 2025, 'survey', None),
        ],
        null_results=[dict(claim='Nordic experts in the same study agreed that a few weeks difference in waiting times does not explain the survival difference.', url=U['khalife'], year=2025)],
        cost=cost(20000, 145000, 'per_100k_pop', 'Per 100 000 residents per year: 1.0 extra GP (130 000 EUR) + 0.1 pulmonologist for e-consultations (15 000 EUR). Setup 20 000 EUR. The roadmap funds this through the national personal doctor programme (measure 2.5.1), no separate budget.'),
        roadmap_measure='2.5.1', roadmap_measures_related=['2.5.2', '3.5.3'],
        owner_fi='Perusterveydenhuollon johtava lääkäri; STM (omalääkäriohjelma)', owner_en='Chief physician of primary care; Ministry of Social Affairs and Health (personal doctor programme)',
        prerequisite_en='Doctors to hire; benefit is not lung-specific, so most of the value lies outside this model.', confidence='low'),
    dict(
        id='smoking_cessation_at_diagnosis', name_en='Smoking cessation started at the first specialist visit', name_fi='Tupakkavieroitus aloitetaan ensikäynnillä',
        step='treatment',
        what_en='Every current smoker with suspected lung cancer gets cessation medication and counselling at the first visit, as part of preparing for curative treatment.',
        what_fi='Jokainen tupakoiva keuhkosyöpäepäilypotilas saa vieroituslääkityksen ja ohjauksen ensikäynnillä osana parantavaan hoitoon valmistautumista.',
        effect=eff('mortality_rr', 0.67, 0.53, 0.85, 'measured', 'Adjusted hazard ratio for all-cause mortality in patients who quit after diagnosis vs those who continued; applies only to current smokers with early-stage (IA-IIIA) NSCLC. Observational. It does not shorten any pathway step (days saved = 0) and its effect on eligibility for curative treatment was not found in an opened source.',
                   applies_to_share_note='current smokers with stage IA-IIIA NSCLC only'),
        evidence=[
            ev('cessation', U['cessation'], 'Quitting after diagnosis: 33 % lower all-cause mortality in early-stage NSCLC.',
               'smoking cessation remained associated with decreased risk for all-cause mortality (HR, 0.67 [95% CI, 0.53 to 0.85]), cancer-specific mortality (HR, 0.75 [CI, 0.58 to 0.98])', 2021, 'prospective cohort, Moscow', 517, access='abstract'),
            ev('paappanen', U['paappanen'], 'Half of potentially operable Finnish patients are not operated, often for lung or heart function.',
               'Among potentially operable patients, 50.6% were deemed ineligible for surgery due to various factors, including poor pulmonary or cardiac function, comorbidities, or localised tumour spread.', 2025, 'retrospective five-hospital cohort, Finland', 545),
        ],
        null_results=[dict(claim='Observational, single country (Russia); patients who manage to quit may differ from those who do not.', url=U['cessation'], year=2021)],
        cost=cost(5000, 400, 'per_patient', 'About 400 EUR per smoking patient: 12 weeks of cessation medication plus three nurse contacts. Setup: training, 5 000 EUR. Prices are assumptions.'),
        roadmap_measure='3.1.2', roadmap_measures_related=[],
        owner_fi='Keuhkosairauksien ylilääkäri ja osastonhoitaja', owner_en='Chief physician and head nurse of pulmonology',
        prerequisite_en='None beyond a standing order; can start tomorrow.', confidence='medium'),
]

# ---------------------------------------------------------------- v3: treatment-access measures
# Each measure below aims at the measured gap: patients who do not get curative-intent treatment.
# No opened study gives a randomised effect on the curative-treatment share, so every effect is kind='assumption';
# the basis text says how the bounds were set from the quoted (observational) figures.
EPMC = 'https://europepmc.org/article/MED/'
U.update({
    'fcr_report': U['fcr'],
    'davison': EPMC + '15237512', 'boxer': EPMC + '21523766', 'freeman': EPMC + '20206544', 'pillay': EPMC + '26643552',
    'lau': EPMC + '23242439', 'rich': EPMC + '21785158',
    'palma': EPMC + '21041709', 'haasbeek': EPMC + '22553198', 'rtog0236': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC6117101/',
    'prehab': EPMC + '36170564', 'schulkes': EPMC + '27349507',
    'crawford': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2743361/', 'jones': EPMC + '18375117',
    'jakobsen': EPMC + '24457234',
})

EV_PAAPPANEN = ev('paappanen', U['paappanen'], 'Half of potentially operable Finnish patients are not operated, often for lung or heart function.',
                  'Among potentially operable patients, 50.6% were deemed ineligible for surgery due to various factors, including poor pulmonary or cardiac function, comorbidities, or localised tumour spread.', 2025, 'retrospective five-hospital cohort, Finland', 545)
EV_YLE_REGIONAL = ev('yle_250979', U['yle2'], 'Curative treatment is delivered less often in Eastern and Northern Finland.',
                     'Syöpärekisterin mukaan Itä- ja Pohjois-Suomessa keuhkosyöpäpotilailla parantava hoito toteutuu harvemmin kuin muualla Suomessa.', 2026, 'news report citing the Finnish Cancer Registry', None)
EV_FCR_RECORDING = ev('fcr_report', U['fcr_report'], 'The registry itself says part of the regional differences comes from recording practice.',
                      'Nämä havainnot viittaavat siihen, että osa alueellisista eroista ei selity yksin potilasrakenteella, vaan myös diagnostiikan, hoitoprosessien ja kirjaamiskäytäntöjen eroilla.', 2026, 'national registry quality report, Finland 2019-2023', 14871)

interventions[-1:-1] = [
    dict(
        id='video_mdt_stage1_3', name_en='Video MDT review of every stage I-III patient with the university hospital', name_fi='Jokaisen I–III-asteen potilaan etä-MDT yliopistosairaalan kanssa',
        step='treatment',
        what_en='Every patient whose cancer has not spread (stage I-III) is discussed by video with the university hospital lung team (surgeon, radiotherapy doctor, oncologist) before anyone decides against treatment that aims to cure. Today a county hospital can decide alone.',
        what_fi='Jokainen potilas, jonka syöpä ei ole levinnyt (aste I–III), käsitellään etäyhteydellä yliopistosairaalan keuhkosyöpätyöryhmässä (kirurgi, sädehoitolääkäri, onkologi) ennen kuin parantavasta hoidosta luovutaan. Nyt keskussairaala voi päättää asiasta yksin.',
        effect=eff('curative_share_pp', 1.5, 0.0, 3.0, 'assumption',
                   'Percentage points added to the share of all lung cancer patients who get curative-intent treatment. No randomised trial exists. In one English district hospital the resection rate rose by 30 % (relative) after a video MDT with the thoracic surgeon started (62 patients a year, before-after). We count a quarter of that on a curative share of about 20 %: 0.25 x 0.30 x 20 = 1.5 points. Upper bound: half of it (3.0). Lower bound 0: an Australian cohort found no difference in surgery between MDT and non-MDT patients, and a systematic review found little evidence that MDT meetings improve outcomes. Counted only in counties that do not host a university hospital.',
                   applies_to='counties without a university hospital'),
        evidence=[
            ev('telemdt_davison', U['davison'], 'A video MDT with the thoracic surgeon in a district hospital: resection rate up 30 % (relative).',
               'The annual resection rate increased by 30% following the introduction of the telemedicine', 2004, 'before-after study, one district general hospital, England', 62, access='abstract'),
            ev('telemdt_davison', U['davison'], 'Same study: time from clinic to surgery fell from 69 to 54 days.',
               'the mean time from first being seen in the clinic to surgery was reduced from 69 to 54 days', 2004, 'before-after study, one district general hospital, England', 62, access='abstract'),
            ev('mdt_boxer', U['boxer'], 'MDT discussion doubled the share who got radiotherapy (66 % vs 33 %) but not surgery.',
               'Treatment receipt for MDT patients versus non-MDT patients was 12% versus 13%, respectively, for surgery (P value nonsignificant); 66% versus 33%, respectively, for radiotherapy (P < .001)', 2011, 'cohort, South Western Sydney, Australia', 988, access='abstract'),
            ev('mdt_freeman', U['freeman'], 'After a thoracic multidisciplinary conference started, guideline-concordant treatment rose from 81 % to 97 % and days to treatment fell from 29 to 17.',
               'adherence to the National Comprehensive Cancer Network (NCCN) treatment guidelines (81%/97%: p<0.0001) all increased significantly while mean days from diagnosis to treatment significantly decreased (29/17: p<0.0001)', 2010, 'before-after study, one US centre (535 patients before, 687 after)', 1222, access='abstract'),
            ev('syopajarjestot', U['syopaj'], 'Whether Finnish patients are discussed in an MDT cannot be measured from national registers today.',
               'eikä hoitoilmoitusrekisteriin kirjattujen tietojen perusteella voida arvioida MDT-toiminnan toteutumista', 2026, 'registry report press release', None),
        ],
        null_results=[
            dict(claim='MDT discussion did not change the share operated (12 % vs 13 %) and did not influence survival (Boxer 2011).', url=U['boxer'], year=2011),
            dict(claim='Systematic review: MDT meetings change management plans, but there is little evidence that they improve clinical outcomes (Pillay 2016).', url=U['pillay'], year=2016),
        ],
        cost=cost(30000, 45000, 'county', 'Setup: video MDT room and image sharing with the university hospital, 30 000 EUR. Yearly: 0.3 coordinator nurse (18 000), 0.1 specialist doctor to prepare cases (15 000), university hospital MDT time bought (12 000). All assumptions.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.3', '3.2.2'],
        owner_fi='Keuhkosairauksien ylilääkäri; yliopistosairaalan keuhkosyövän MDT-vastaava', owner_en='Chief physician of pulmonology; lead of the university hospital lung MDT',
        prerequisite_en='The university hospital agrees a weekly video slot. Roadmap 3.1.2 expects regional pathway responsibilities to be agreed in collaborative-area contracts by 2028.', confidence='low'),
    dict(
        id='surgeon_second_opinion', name_en='Thoracic surgeon reviews every decision not to operate', name_fi='Thoraxkirurgi arvioi jokaisen päätöksen jättää leikkaamatta',
        step='treatment',
        what_en='A thoracic surgeon from the university hospital sits in the county lung meeting every week and gives a second opinion before a stage I-II patient is refused surgery. Counties without their own thoracic surgeon decide about surgery without one today.',
        what_fi='Yliopistosairaalan thoraxkirurgi osallistuu viikoittain alueen keuhkosyöpäkokoukseen ja antaa toisen arvion ennen kuin I–II-asteen potilas jätetään leikkaamatta. Alueet, joilla ei ole omaa thoraxkirurgia, tekevät nyt leikkauspäätökset ilman kirurgia.',
        effect=eff('curative_share_pp', 1.2, 0.0, 2.4, 'assumption',
                   'Percentage points added to the share of all patients treated with curative intent, through more operations. In England, units where a surgeon attended more than two-thirds of the lung MDT meetings operated on 14.4 % of patients against 12.0 % elsewhere: a difference of 2.4 points (observational, units differ in other ways). We count half (1.2); upper bound the full difference (2.4); lower bound 0. Counted only in counties that do not host a university hospital.',
                   applies_to='counties without a university hospital'),
        evidence=[
            ev('lau_surgeons', U['lau'], 'Units where surgeons attended more than two-thirds of lung MDT meetings operated on 14.4 % vs 12.0 %.',
               'where surgeons were present in more than two-thirds of the lung cancer multidisciplinary team meetings (14.4% versus 12.0%, p = 0.046)', 2013, 'retrospective observational study, national audit linked to surgeon workforce data, England 2008-2009', None, access='abstract'),
            ev('lau_surgeons', U['lau'], 'Units that added specialist thoracic surgeons raised their resection rate more (relative rise 66 % vs 19 %).',
               'Four units increased their number of specialist thoracic surgeons and had a significantly higher increase in resection rate than units without expansion (relative rise 66.3% versus 19.2%; p = 0.022).', 2013, 'national survey linked to audit data, England', None, access='abstract'),
            ev('rich_nlca', U['rich'], 'Patients first seen in a thoracic surgical centre were 51 % more likely to be operated (17 % vs 13 %).',
               'patients with NSCLC first seen in thoracic surgical centres (27% of the cohort) were 51% more likely to have surgery than those seen in non-surgical centres (adjusted OR 1.51, 95% CI 1.16 to 1.97). Resection rates varied from 13% to 17% between non-surgical and thoracic surgical centres.', 2011, 'national audit cohort, England', 34513, access='abstract'),
            EV_PAAPPANEN,
        ],
        null_results=[dict(claim='Observational comparisons of hospitals: units where surgeons attend differ in other ways too. In an Australian cohort, patients discussed in an MDT were not operated more often than others (12 % vs 13 %, Boxer 2011).', url=U['boxer'], year=2011)],
        cost=cost(5000, 40000, 'county', 'Yearly: 0.2 thoracic surgeon bought from the university hospital (0.2 x 150 000 = 30 000) and 10 000 for case preparation. Setup 5 000. All assumptions.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.1'],
        owner_fi='Keuhkosairauksien ylilääkäri; yliopistosairaalan thoraxkirurgian ylilääkäri', owner_en='Chief physician of pulmonology; chief of thoracic surgery at the university hospital',
        prerequisite_en='Surgeon time at the university hospital (there are few thoracic surgeons; roadmap 3.5.1 names staffing as a need) and operating capacity for the extra patients.', confidence='medium'),
    dict(
        id='sbrt_pathway', name_en='Stereotactic radiotherapy pathway for early cancer in patients who cannot be operated', name_fi='Stereotaktisen sädehoidon polku varhaisvaiheen potilaille, joita ei voida leikata',
        step='treatment',
        what_en='Every stage I patient who is too frail for surgery is referred for stereotactic radiotherapy (3-8 visits, no anaesthesia) instead of being left without treatment. The treatment exists in every university hospital; what is missing in some counties is the referral rule.',
        what_fi='Jokainen I-asteen potilas, joka ei kestä leikkausta, lähetetään stereotaktiseen sädehoitoon (3–8 käyntiä, ei nukutusta) sen sijaan, että hän jää hoidotta. Hoitoa annetaan kaikissa yliopistosairaaloissa; osalta alueista puuttuu lähettämisen sääntö.',
        effect=eff('curative_share_pp', 0.8, 0.0, 1.6, 'assumption',
                   'Percentage points added to the share of all patients treated with curative intent, through radiotherapy. In the Netherlands the share of elderly stage I patients left untreated fell by 7 points nationally (and radiotherapy use rose 16 points in one province) when stereotactic radiotherapy became available. Elderly stage I patients are roughly 8 % of all lung cancer patients (our assumption; no county table by stage and age is published): 7 to 16 points x 8 % = 0.6 to 1.3 points. Finland already gives this treatment, so the gain exists only where a county refers fewer patients than the rest; we use 0.8 with bounds 0 and 1.6.'),
        evidence=[
            ev('sbrt_haasbeek', U['haasbeek'], 'Netherlands, elderly stage I patients: 7 points fewer untreated after stereotactic radiotherapy became available; surgery unchanged.',
               'Between period A and C, there was a 7% absolute reduction in patients going untreated, corresponding to an 8-month improvement in median survival (P < 0.001). Radiotherapy utilization increased from 31% to 38%, whereas surgical utilization remained constant (37%).', 2012, 'population registry, Netherlands, elderly stage I patients', 4605, access='abstract'),
            ev('sbrt_palma', U['palma'], 'North Holland: radiotherapy use in elderly stage I patients rose 16 points and fewer went untreated.',
               'SBRT introduction was associated with a 16% absolute increase in RT use, a decline in the proportion of untreated elderly patients, and an improvement in OS.', 2010, 'population registry, North Holland, patients aged 75+', 875, access='abstract'),
            ev('rtog0236', U['rtog0236'], 'Medically inoperable stage I patients treated with stereotactic radiotherapy: 40 % alive at five years.',
               'Disease-free survival and overall survival at 5 years was 25.5% (95% CI, 14.9%-37.4%) and 40.0% (95% CI, 27.1%-52.5%), respectively', 2018, 'single-arm phase 2 trial (RTOG 0236)', 55),
            ev('raz_untreated', EPMC + '17505036', 'Untreated stage I patients: 6 % alive at five years.',
               'Five-year OS for untreated stage I NSCLC was 6% overall, 9% for T1 tumors, and 11% for patients who refused surgical resection.', 2007, 'population registry, California', 1432, access='abstract'),
        ],
        null_results=[dict(claim='No randomised comparison of stereotactic radiotherapy with no treatment exists; the Dutch figures are before-after changes in a registry, and the patients in the trial were selected.', url=U['haasbeek'], year=2012)],
        cost=cost(10000, 200, 'per_patient', 'Per newly diagnosed lung cancer patient per year: about 1 extra treatment course per 100 patients x 6 000 EUR = 60 EUR, lung function tests and PET-CT for the 5 in 100 assessed x 1 500 EUR = 75 EUR, referral coordination 65 EUR. Setup: referral rule and training, 10 000 EUR. Prices are assumptions.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.1.4'],
        owner_fi='Syöpätautien ylilääkäri; yliopistosairaalan sädehoidon ylilääkäri', owner_en='Chief physician of oncology; chief of radiotherapy at the university hospital',
        prerequisite_en='Radiotherapy slots at the university hospital and PET-CT for staging.', confidence='medium'),
    dict(
        id='prehab_fitness_assessment', name_en='Fitness assessment and prehabilitation before deciding against curative treatment', name_fi='Toimintakyvyn arvio ja esikuntoutus ennen kuin parantavasta hoidosta luovutaan',
        step='treatment',
        what_en='Before a stage I-III patient is judged too frail, they get an exercise test, a geriatric assessment if over 75, and four weeks of supervised exercise, breathing training and help to stop smoking. Then the decision is made again.',
        what_fi='Ennen kuin I–III-asteen potilas todetaan liian huonokuntoiseksi, hänelle tehdään rasituskoe, yli 75-vuotiaalle geriatrinen arvio ja järjestetään neljän viikon ohjattu liikunta, hengitysharjoittelu ja tupakkavieroitus. Sen jälkeen päätös tehdään uudelleen.',
        effect=eff('curative_share_pp', 0.5, 0.0, 1.5, 'assumption',
                   'Percentage points added to the share of all patients treated with curative intent. No opened study measures how many more patients become fit for curative treatment. In five Finnish hospitals half (50.6 %) of potentially operable patients were judged not fit for surgery. If potentially operable patients are about 20 % of all patients and 1 in 20 of those refused became eligible: 20 x 0.506 x 0.05 = 0.5 points; upper bound 3 in 20 (1.5); lower bound 0. What trials do show is fewer complications after surgery, not more patients treated.'),
        evidence=[
            EV_PAAPPANEN,
            ev('prehab_cochrane', U['prehab'], 'Exercise training before lung surgery more than halves lung complications after it.',
               'Preoperative exercise training results in a large reduction in the risk of developing a postoperative pulmonary complication compared to no preoperative exercise training (risk ratio (RR) 0.45, 95% CI 0.33 to 0.61', 2022, 'Cochrane systematic review, 10 randomised trials', 636, access='abstract'),
            ev('cga_schulkes', U['schulkes'], 'Geriatric assessment in lung cancer patients changed treatment decisions.',
               'The information revealed by a geriatric assessment led to changes in oncologic treatment and nononcologic interventions.', 2016, 'systematic review, 18 studies', None, access='abstract'),
        ],
        null_results=[dict(claim='The Cochrane review measures complications and exercise capacity in patients already accepted for surgery; it does not show that more patients get operated.', url=U['prehab'], year=2022)],
        cost=cost(10000, 250, 'per_patient', 'Per newly diagnosed patient per year: about 15 in 100 patients assessed x 1 500 EUR (exercise test, geriatric assessment, four weeks of physiotherapy) = 225 EUR, plus coordination. Setup: training, 10 000 EUR. Prices are assumptions.'),
        roadmap_measure='3.5.4', roadmap_measures_related=['3.1.2'],
        owner_fi='Keuhkosairauksien ylilääkäri; kuntoutuksen ja geriatrian vastuulääkärit', owner_en='Chief physician of pulmonology; leads of rehabilitation and geriatrics',
        prerequisite_en='Physiotherapy and geriatric capacity; four weeks of preparation must not push treatment past the target time.', confidence='low'),
    dict(
        id='travel_accommodation_support', name_en='Travel and accommodation support for patients far from the university hospital', name_fi='Matka- ja majoitustuki kaukana yliopistosairaalasta asuville',
        step='treatment',
        what_en='Patients who must travel for surgery or weeks of radiotherapy get a booked patient hotel, organised transport and a named contact, so that distance is not the reason to choose a non-curative treatment.',
        what_fi='Leikkaukseen tai viikkojen sädehoitoon matkustavalle potilaalle varataan potilashotelli, järjestetään kuljetus ja nimetään yhteyshenkilö, jotta välimatka ei ole syy valita muuta kuin parantava hoito.',
        effect=eff('curative_share_pp', 1.0, 0.0, 2.0, 'assumption',
                   'Percentage points added to the share of all patients treated with curative intent, at full distance (county centre 200 km or more from the university hospital); scaled down to 0 at 50 km. No study of travel support was opened. The reason to act is an association: in England patients with the longest travel time to hospital had odds of surgery 0.60 times those of the nearest, and in Finland the curative share falls with distance to the university hospital (Spearman -0.66 across counties, weaker after allowing for age). Removing a quarter of a gap of about 4 points gives 1.0; bounds 0 and 2.0. The distance association must not be read as the effect of this measure.',
                   applies_to='scaled by road distance from county centre to university hospital: 0 at 50 km, full at 200 km'),
        evidence=[
            ev('travel_crawford', U['crawford'], 'England: the longer the travel time to hospital, the lower the odds of lung cancer surgery (0.88, 0.74, 0.60).',
               'Odds ratios for undergoing surgery for non-small cell lung cancer using (1) travel time to diagnosing hospital were 0.88 (0.70-1.11), 0.74 (0.59-0.94) and 0.60 (0.44-0.84).', 2009, 'cancer registry cohort, Northern England', 34923),
            ev('travel_jones', U['jones'], 'Patients living further from a thoracic surgery hospital were less likely to be operated.',
               'Lung cancer patients living further from a thoracic surgery hospital were less likely to receive surgery, and both lung cancer and rectal cancer patients were less likely to receive chemotherapy if they lived distant from these services.', 2008, 'cancer registry cohort, Northern England', None, access='abstract'),
            ev('ostrobothnia', U['ostro'], 'Ostrobothnia: patients living over 50 km from the hospital had higher 12-month mortality.',
               'the adjusted HR increased to 1.47 (95% CI: 1.07–2.01; p = 0.017) for patients living in rural areas compared to those in urban areas', 2024, 'population-based single-hospital cohort, Vaasa 2016-2020', 321),
            EV_YLE_REGIONAL,
        ],
        null_results=[
            dict(claim='No intervention study: every figure here is an association between distance and treatment, not the effect of paying for travel.', url=U['crawford'], year=2009),
            dict(claim='The Ostrobothnia paper notes that an Australian and a Polish study found no association between distance and survival.', url=U['ostro'], year=2024),
        ],
        cost=cost(5000, 300, 'per_patient', 'Per newly diagnosed patient per year: about 30 in 100 patients travel for curative work-up or treatment x 1 000 EUR (patient hotel nights and organised transport beyond what Kela reimburses) = 300 EUR. Setup 5 000 EUR. Patient numbers and prices are assumptions.'),
        roadmap_measure='3.1.2', roadmap_measures_related=['3.5.4'],
        owner_fi='Syöpätautien ylilääkäri ja sosiaalityö; yliopistosairaalan potilashotelli', owner_en='Chief physician of oncology and hospital social work; university hospital patient hotel',
        prerequisite_en='Patient hotel capacity near the university hospital.', confidence='low'),
    dict(
        id='recording_audit', name_en='Audit of treatment records ("no treatment on record")', name_fi='Hoitotietojen kirjaamisen auditointi ("ei hoitotietoa")',
        step='treatment',
        what_en='Take 50 patients with no treatment on record and check the charts: were they untreated, or was drug treatment or radiotherapy given and not coded? Fix the coding. It treats no extra patient, but until it is done the county cannot tell a care gap from a recording gap.',
        what_fi='Poimitaan 50 potilasta, joilta hoitotieto puuttuu, ja tarkistetaan potilaskertomuksista, jäivätkö he hoidotta vai jäikö lääke- tai sädehoito kirjaamatta. Kirjaaminen korjataan. Yhtään uutta potilasta ei hoideta, mutta sitä ennen alue ei voi erottaa hoitovajetta kirjaamisvajeesta.',
        effect=eff('curative_share_pp', 0.0, 0.0, 0.0, 'assumption', 'Adds no treated patients and avoids no deaths; the model counts zero. Its value is that the county can trust its own care path. Bought first in counties where "no treatment on record" is far above the national share while life-prolonging treatment is far below it.',
                   applies_to='counties with a recording flag on the care path'),
        evidence=[
            EV_FCR_RECORDING,
            ev('fcr_report', U['fcr_report'], 'Treatment data linked to a lung cancer visit was found for 72.5 % of patients nationally.',
               'Keuhkosyöpäkäyntiin liittyvä hoitotieto löytyi 10 784 potilaalta (72,5 %).', 2026, 'national registry quality report, Finland 2019-2023', 14871),
            ev('syopajarjestot', U['syopaj'], 'Stage was missing for nearly half of patients, which the registry attributes to gaps in clinical cancer notifications.',
               'Levinneisyystieto puuttui lähes puolelta potilaista, mikä kertoo puutteista kliinisten syöpäilmoitusten kirjaamisessa.', 2026, 'registry report press release', None),
            ev('dlcr_jakobsen', U['jakobsen'], 'Denmark: a national lung cancer registry with quarterly reports and yearly audit went together with rising resection rates and survival.',
               'Five-year survival after surgical resection has increased from 39.5% to 48.1%. Improvements of waiting times, accordance between cTNM and pTNM, and resection rates are documented.', 2013, 'national clinical registry report, Denmark, 2000-2012', 40000, access='abstract'),
        ],
        null_results=[dict(claim='An audit by itself changes no treatment. The Danish improvements happened alongside pathways and centralisation, so they cannot be credited to the registry alone.', url=U['jakobsen'], year=2013)],
        cost=cost(15000, 5000, 'county', 'Setup: about 0.2 person-years of a coding nurse and a clinician to review 50 charts and correct the coding rules, 15 000 EUR. Yearly: a repeat sample, 5 000 EUR. Assumptions.'),
        roadmap_measure='3.2.2', roadmap_measures_related=['3.2.1', '3.1.4'],
        owner_fi='Syöpätautien ylilääkäri ja tietohallinnon kirjaamisvastaava', owner_en='Chief physician of oncology and the head of clinical coding',
        prerequisite_en='None; it can start this week.', confidence='medium'),
]

# ---------------------------------------------------------------- v3 fields for every measure
# owner_level: who can decide. targets_stage: care-path stage id (None = before diagnosis, not on the measured care path).
# modality: which part of curative treatment a curative_share_pp gain comes through (surgery | radiotherapy | any | None).
# kpi.baseline_from: where the app reads the county's current value; None = Finland does not publish it, start recording.
# kpi.target.type: plus_gain = baseline + the gain the model expects from this measure; national = reach the national value;
#                  fixed = the stated value (our target, an assumption); record = no baseline exists, the first target is to have one.
def kpi(indicator, label_en, label_fi, baseline_from, rule, ttype, by_year, value=None):
    t = {'type': ttype}
    if value is not None:
        t['value'] = value
    return dict(indicator=indicator, label_en=label_en, label_fi=label_fi, baseline_from=baseline_from, target_rule_en=rule, target=t, by_year=by_year)


KPI_CUR = lambda: kpi('curative_intent_pct', 'Share of patients who get treatment that aims to cure', 'Parantavaan hoitoon ohjautuneiden osuus', 'care_path.curative',
                      'county share today plus the points this measure is expected to add; never above the best county', 'plus_gain', 2028)
KPI_SURG = lambda: kpi('surgery_pct', 'Share of patients operated', 'Leikattujen osuus', 'care_path.surgery',
                       'county share today plus the points this measure is expected to add', 'plus_gain', 2028)
KPI_TIME = lambda: kpi('dx_to_treatment_days', 'Days from diagnosis to start of treatment (median)', 'Päivät diagnoosista hoidon alkuun (mediaani)', 'care_path.time_to_treatment',
                       'at or below the national median; published for the collaborative area, so the county must start reporting its own', 'national', 2028)

V3 = {
    'cpp_pathway': dict(owner_level='county', targets_stage='time_to_treatment', modality=None,
        first_step_en='Name one pathway owner and book fixed weekly CT, PET-CT, bronchoscopy and MDT slots for suspected lung cancer.',
        first_step_fi='Nimetään hoitopolulle vastuuhenkilö ja varataan keuhkosyöpäepäilyille kiinteät viikoittaiset TT-, PET-TT-, bronkoskopia- ja MDT-ajat.', kpi=KPI_TIME()),
    'same_day_cxr_ct': dict(owner_level='county', targets_stage=None, modality=None,
        first_step_en='Agree with radiology that a suspicious chest X-ray is followed by CT the same day, without a new referral.',
        first_step_fi='Sovitaan kuvantamisen kanssa, että epäilyttävän keuhkokuvan jälkeen TT tehdään samana päivänä ilman uutta lähetettä.',
        kpi=kpi('cxr_to_ct_days', 'Days from suspicious chest X-ray to CT', 'Päivät epäilyttävästä keuhkokuvasta TT-kuvaukseen', None, 'not published in Finland: record it from this month; target 3 days or less (our target)', 'fixed', 2027, 3)),
    'gp_direct_ct': dict(owner_level='county', targets_stage=None, modality=None,
        first_step_en='Open chest CT ordering to health centre doctors for named symptoms and reserve the CT slots.',
        first_step_fi='Avataan terveyskeskuslääkäreille oikeus tilata keuhkojen TT nimetyillä oireilla ja varataan kuvausajat.',
        kpi=kpi('gp_visit_to_ct_days', 'Days from first GP visit to CT', 'Päivät ensimmäisestä terveyskeskuskäynnistä TT-kuvaukseen', None, 'not published in Finland: record it from this month; target 14 days or less (our target)', 'fixed', 2027, 14)),
    'ai_cxr_triage_alone': dict(owner_level='county', targets_stage=None, modality=None,
        first_step_en='Do not buy it alone: first check how many days a flagged X-ray waits for CT.',
        first_step_fi='Ei hankita yksinään: selvitetään ensin, montako päivää poikkeava keuhkokuva odottaa TT-kuvausta.',
        kpi=kpi('cxr_to_ct_days', 'Days from suspicious chest X-ray to CT', 'Päivät epäilyttävästä keuhkokuvasta TT-kuvaukseen', None, 'not published in Finland: record it', 'record', 2027)),
    'ebus_capacity': dict(owner_level='county', targets_stage='staged', modality=None,
        first_step_en='Count how many patients waited over a week for bronchoscopy last quarter and add one EBUS list a week.',
        first_step_fi='Lasketaan, kuinka moni odotti bronkoskopiaa yli viikon viime neljänneksellä, ja lisätään yksi EBUS-lista viikossa.',
        kpi=kpi('stage_recorded_pct', 'Share of patients with stage recorded', 'Levinneisyystieto kirjattu, osuus potilaista', 'care_path.staged', 'reach the best county', 'best', 2028)),
    'reflex_molecular': dict(owner_level='county', targets_stage='drug_therapy', modality=None,
        first_step_en='The chief pathologist and the chief oncologist sign a standing order: every new non-small cell lung cancer sample goes to EGFR, ALK and PD-L1 testing the day it is diagnosed.',
        first_step_fi='Patologian ja syöpätautien ylilääkärit allekirjoittavat pysyväismääräyksen: jokaisesta uudesta ei-pienisoluisesta keuhkosyöpänäytteestä tehdään EGFR-, ALK- ja PD-L1-tutkimukset diagnoosipäivänä.',
        kpi=kpi('dx_to_biomarker_days', 'Days from tissue diagnosis to complete biomarker result; days to first drug treatment', 'Päivät kudosdiagnoosista biomarkkerivastaukseen; päivät ensimmäiseen lääkehoitoon', None,
                'not published in Finland: record it from this month; target 10 working days or less (our target, no Finnish standard was found)', 'fixed', 2027, 10)),
    'liquid_biopsy_first': dict(owner_level='county', targets_stage='drug_therapy', modality=None,
        first_step_en='Agree with the laboratory which patients with suspected advanced cancer get a plasma test at the first visit.',
        first_step_fi='Sovitaan laboratorion kanssa, keille levinnyttä syöpää epäiltäessä otetaan plasmanäyte ensikäynnillä.',
        kpi=kpi('dx_to_biomarker_days', 'Days from first specialist visit to biomarker result', 'Päivät ensikäynnistä biomarkkerivastaukseen', None, 'not published in Finland: record it', 'record', 2027)),
    'nurse_navigator': dict(owner_level='county', targets_stage='time_to_treatment', modality=None,
        first_step_en='Name one nurse who books every test for each new suspected lung cancer patient and calls the patient with the dates.',
        first_step_fi='Nimetään hoitaja, joka varaa jokaisen uuden keuhkosyöpäepäilyn tutkimukset ja ilmoittaa ajat potilaalle.', kpi=KPI_TIME()),
    'ldct_screening': dict(owner_level='national', targets_stage=None, modality=None,
        first_step_en='Not a county decision. Ask the Ministry and Palko for the timetable after the 2026-2028 pilot and offer the county as a pilot site.',
        first_step_fi='Ei hyvinvointialueen päätös. Pyydetään STM:ltä ja Palkolta aikataulu pilotin 2026–2028 jälkeen ja tarjoudutaan pilottialueeksi.',
        kpi=kpi('screening_participants', 'People screened per year; share of cancers found at stage I', 'Seulottuja vuodessa; I-asteessa todettujen osuus', None, 'set by the national programme after the pilot', 'record', 2028)),
    'symptom_campaign': dict(owner_level='county', targets_stage='staged', modality=None,
        first_step_en='Before buying advertising, check that health centres can see the extra patients within a week.',
        first_step_fi='Ennen mainonnan ostamista varmistetaan, että terveyskeskukset pystyvät ottamaan lisäpotilaat vastaan viikon sisällä.',
        kpi=kpi('stage_1_share_pct', 'Share of cancers found at stage I', 'I-asteessa todettujen osuus', None, 'not published per county (stage is missing for nearly half of patients): record it', 'record', 2028)),
    'nssc_rapid_dx_centre': dict(owner_level='county', targets_stage=None, modality=None,
        first_step_en='Name the unit and the doctor who take patients with unexplained weight loss or fatigue within a week.',
        first_step_fi='Nimetään yksikkö ja lääkäri, joka ottaa selittämättömästä laihtumisesta tai väsymyksestä kärsivät potilaat vastaan viikon sisällä.',
        kpi=kpi('referral_to_diagnosis_days', 'Days from referral to diagnosis', 'Päivät lähetteestä diagnoosiin', None, 'not published in Finland: record it', 'record', 2027)),
    'gp_capacity_econsult': dict(owner_level='county', targets_stage=None, modality=None,
        first_step_en='Open an e-consultation line from health centre doctors to a pulmonologist with an answer within two working days.',
        first_step_fi='Avataan terveyskeskuslääkäreille e-konsultaatio keuhkolääkärille; vastaus kahden arkipäivän kuluessa.',
        kpi=kpi('primary_care_wait_over_7d_pct', 'Share of primary care visits that waited over 7 days', 'Yli 7 päivää odottaneiden osuus perusterveydenhuollon käynneistä', None, 'at or below the national share', 'national', 2028)),
    'smoking_cessation_at_diagnosis': dict(owner_level='county', targets_stage='curative', modality=None,
        first_step_en='Write the standing order: every smoker with suspected lung cancer leaves the first visit with cessation medicine and a nurse call booked.',
        first_step_fi='Kirjoitetaan pysyväismääräys: jokainen tupakoiva keuhkosyöpäepäilypotilas saa ensikäynnillä vieroituslääkkeen ja ajan hoitajan soittoon.',
        kpi=kpi('cessation_offered_pct', 'Share of smoking patients given cessation medicine at the first visit', 'Vieroituslääkityksen ensikäynnillä saaneiden osuus tupakoivista', None, 'not published in Finland: record it; target 90 % (our target)', 'fixed', 2027, 90)),
    'video_mdt_stage1_3': dict(owner_level='collaborative_area', targets_stage='curative', modality='any',
        first_step_en='Ask the university hospital for a fixed weekly video slot and list every stage I-III patient diagnosed last month who was not discussed there.',
        first_step_fi='Pyydetään yliopistosairaalalta kiinteä viikoittainen etäkokousaika ja listataan viime kuussa todetut I–III-asteen potilaat, joita siellä ei käsitelty.', kpi=KPI_CUR()),
    'surgeon_second_opinion': dict(owner_level='collaborative_area', targets_stage='surgery', modality='surgery',
        first_step_en='Agree with the university hospital that a thoracic surgeon joins the weekly lung meeting, and send last quarter\'s stage I-II patients who were not operated for a second look.',
        first_step_fi='Sovitaan yliopistosairaalan kanssa, että thoraxkirurgi osallistuu viikoittaiseen keuhkosyöpäkokoukseen, ja lähetetään viime neljänneksen leikkaamatta jääneet I–II-asteen potilaat uuteen arvioon.', kpi=KPI_SURG()),
    'sbrt_pathway': dict(owner_level='county', targets_stage='radiotherapy', modality='radiotherapy',
        first_step_en='Write the referral rule: every stage I patient not accepted for surgery is referred for stereotactic radiotherapy the same week.',
        first_step_fi='Kirjataan lähettämisen sääntö: jokainen I-asteen potilas, jota ei hyväksytä leikkaukseen, lähetetään samalla viikolla stereotaktiseen sädehoitoon.', kpi=KPI_CUR()),
    'prehab_fitness_assessment': dict(owner_level='county', targets_stage='curative', modality='any',
        first_step_en='Decide that no stage I-III patient is recorded as "not fit" without an exercise test, and book the physiotherapy group.',
        first_step_fi='Päätetään, ettei yhtäkään I–III-asteen potilasta kirjata hoitoon soveltumattomaksi ilman rasituskoetta, ja varataan fysioterapiaryhmä.', kpi=KPI_CUR()),
    'travel_accommodation_support': dict(owner_level='county', targets_stage='curative', modality='any',
        first_step_en='Name one contact person who books the patient hotel and transport for every patient sent to the university hospital for curative treatment.',
        first_step_fi='Nimetään yhteyshenkilö, joka varaa potilashotellin ja kuljetuksen jokaiselle parantavaan hoitoon yliopistosairaalaan lähetettävälle.', kpi=KPI_CUR()),
    'recording_audit': dict(owner_level='county', targets_stage='no_record', modality=None,
        first_step_en='Pull 50 patients diagnosed in 2023 with no treatment on record and check their charts this month.',
        first_step_fi='Poimitaan 50 vuonna 2023 todettua potilasta, joilta hoitotieto puuttuu, ja tarkistetaan heidän potilaskertomuksensa tämän kuun aikana.',
        kpi=kpi('no_treatment_record_pct', 'Share of patients with no treatment on record', 'Potilaat, joilta hoitotieto puuttuu, osuus', 'care_path.no_record', 'at or below the national share once coding is corrected', 'national', 2027)),
}
_missing = [i['id'] for i in interventions if i['id'] not in V3]
assert not _missing, _missing
for i in interventions:
    i.update(V3[i['id']])

# ---------------------------------------------------------------- roadmap
raw = json.load(open(OUT + '/_tools/roadmap_raw.json', encoding='utf-8'))
EN = {
    '1.3.2': ('Promote early presentation with a national communication plan that raises awareness of cancer symptoms', 'A national symptom-awareness communication plan, drawing on examples such as the UK Be Clear on Cancer campaign aimed at groups with delayed presentation.'),
    '2.3.1': ('Clarify the division of work between the national screening steering group, programme expert groups and the Palko screening section', 'Defines a permanent official structure, process and timetable for planning and steering cancer screening.'),
    '2.3.2': ('Update the criteria for decisions on cancer screening programmes', 'Updates the 2006 decision criteria and evidence requirements for new and existing screening programmes (mortality effect, harms, cost-effectiveness).'),
    '2.3.3': ('Extend breast cancer screening to ages 46-74', 'Extends the breast screening target age from 50-69 to 46-74.'),
    '2.3.4': ('Establish new national screening programmes and adapt existing ones based on research and EU recommendations', 'Covers the lung cancer screening pilot for long-term smokers (started early 2026) and the prostate screening decision; lung pilot to expand regionally by 2028.'),
    '2.5.1': ('Improve access to care by adding doctor capacity in primary care, for example by extending the personal doctor model nationwide', 'Strengthens doctor availability and continuity of care in primary care as a condition for early detection; delivered through the national personal doctor programme.'),
    '2.5.2': ('Support smooth transfer to specialist care by defining standard referral criteria in the national pathways, so patients with possible cancer symptoms are sent quickly to diagnostic tests', 'Standard referral criteria and symptom-based operating models written into national cancer pathway descriptions, for at least the five most common cancers by 2028.'),
    '2.5.3': ('Create operating models for identifying cancer risk groups and improving early diagnosis using genetic information', 'National programme on using genetic information to find high-risk people; report by 2028, regional pilots 2029-2031.'),
    '3.1.1': ('Create a national mechanism and permanent funding for maintaining cancer-specific care guidelines', 'Nationally coordinated mechanism (as in Denmark, Sweden, Norway) for writing and updating cancer guidelines; 5 MEUR a year also funds measures 2.5.2, 3.1.2, 3.1.3, 3.1.4 and 4.3.2.'),
    '3.1.2': ('Write cancer-specific care pathway descriptions, regional pathways based on them, and a mechanism to maintain them', 'National pathway descriptions on the model of Danish Kræftpakkeforløb, Swedish SVF and Norwegian Pakkeforløp; five cancers and cancer-specific access-time targets by 2028.'),
    '3.1.3': ('Create nationally uniform policies for taking costs and other societal effects into account in treatment choices', 'Applies the service-range principles of the Ministry to cancer guidelines and pathways.'),
    '3.1.4': ('Define national quality and effectiveness targets and follow-up indicators so that pathways can be monitored', 'Cancer-specific quality and effectiveness targets and indicators for at least the five largest cancer groups by 2028.'),
    '3.2.1': ('Create the legal basis for a cancer care quality register at the THL Cancer Registry', 'National cancer quality register; five cancers first; target 90 % data coverage including stage.'),
    '3.2.2': ('Define and start peer-development processes in which quality register data are compared and reviewed systematically', 'Benchmarking between wellbeing services counties to find development needs and share good practice.'),
    '3.2.3': ('Define and start steering and management mechanisms for reacting to peer-review results and shortcomings', 'Uniform structures for reviewing results and reacting to deviations regionally and nationally.'),
    '3.2.4': ('Clarify roles and responsibilities in cancer quality register work, create a contractual basis and secure permanent funding', 'Roles, contracts and permanent funding for the quality register.'),
    '3.5.1': ('Create sustainable strategies to ensure enough staff for cancer care', 'Realistic assessment of staffing and training needs in cancer diagnostics (especially molecular diagnostics) and care; county workforce plans.'),
    '3.5.2': ('Develop and increase continuing education and specialisation for cancer professionals and define uniform national job titles', 'Continuing education and specialisation in all key professions; uniform titles and competence requirements for cancer nursing staff.'),
    '3.5.3': ('Promote the adoption and development of digital tools, AI and innovations in cancer care', 'Digital care pathways, remote monitoring and AI tools to support early detection, coordination and continuity from primary to specialist care.'),
    '3.5.4': ('Strengthen competence in psychosocial support, rehabilitation, geriatric oncology and palliative care at all stages of cancer care', 'Curriculum and continuing-education development in these areas.'),
    '3.5.5': ('Start specialist training in palliative medicine', 'New medical specialty training programme in palliative medicine.'),
}
measures = []
for m in raw:
    f = m['fields']
    res = ' '.join(v for _, v in f.get('Resurssi', []))
    bm = re.search(r'määräraha ([\d  ]+)€', res)
    budget = int(re.sub(r'\D', '', bm.group(1))) if bm else None
    measures.append(dict(
        id=m['id'], title_fi=m['title_fi'], title_en=EN[m['id']][0], summary_en=EN[m['id']][1],
        responsible=' | '.join(v for _, v in f.get('Vastuutaho', [])) or None,
        schedule=' | '.join(v for _, v in f.get('Aikataulu', [])) or None,
        budget_eur=budget, budget_text_fi=res or None,
        indicator=[v for _, v in f.get('Mittari', [])] or None,
        quote_fi=m['body_head'][:400],
        line_ref=dict(file='res/roadmap/r.txt', start=m['line_start'], end=m['line_end'],
                      responsible=[n for n, _ in f.get('Vastuutaho', [])], resource=[n for n, _ in f.get('Resurssi', [])],
                      schedule=[n for n, _ in f.get('Aikataulu', [])], indicator=[n for n, _ in f.get('Mittari', [])]),
        used_by_interventions=sorted(i['id'] for i in interventions if i['roadmap_measure'] == m['id'] or m['id'] in i.get('roadmap_measures_related', [])),
        verified=True,
    ))
S = open(ROOT + '/res/strategy/s.txt', encoding='utf-8').read().split('\n')
def sline(pat):
    for i, l in enumerate(S):
        if pat in l:
            return i + 1
    raise SystemExit('strategy line not found: ' + pat)
def sind(text_fi, text_en, pat):
    return dict(text_fi=text_fi, text_en=text_en, line_ref=dict(file='res/strategy/s.txt', line=sline(pat)), verified=True)
roadmap = {
    '_meta': {'source_roadmap': 'res/roadmap/r.txt (Kansallinen syöpästrategia 2026–2035: Toimeenpanon tiekartta vuosille 2026–2031)', 'source_strategy': 'res/strategy/s.txt (Kansallinen syöpästrategia 2026–2035)', 'built_at': FETCHED,
              'note': 'Finnish fields are copied from the text with line-break hyphens left as in the extracted text. title_en and summary_en are our translations. budget_eur is the figure after "Arvioitu tarvittava määräraha"; null means the roadmap states no separate amount (see budget_text_fi).'},
    'measures': measures,
    'strategy_indicators': {
        'goal_2': {
            'title_fi': 'Vähennetään syöpätaakkaa ehkäisyn ja varhaisen toteamisen avulla', 'title_en': 'Reduce the cancer burden through prevention and early detection',
            'indicators': [
                sind('Ehkäistävien syöpien määrä laskee 1000 tapauksella vuodessa*', 'The number of preventable cancers falls by 1,000 cases a year', 'Ehkäistävien syöpien määrä laskee'),
                sind('Kaikissa syöpäseulontaohjelmissa saavutetaan 80 %:n osallistumisaste jokaisella hyvinvointialueella', 'Every cancer screening programme reaches 80 % participation in every wellbeing services county', 'Kaikissa syöpäseulontaohjelmissa saavutetaan'),
                sind('Vähintään 70 % syövistä diagnosoidaan levinneisyysluokissa I-II', 'At least 70 % of cancers are diagnosed at stage I-II', 'Vähintään 70 % syövistä diagnosoidaan'),
            ]},
        'goal_3': {
            'title_fi': 'Varmistetaan yhdenvertainen ja vaikuttava syövänhoito', 'title_en': 'Ensure equal and effective cancer care',
            'indicators': [
                sind('Huonoennusteisten syöpien 5 vuoden elossaololuvut saavuttavat pohjoismaisen tason**', 'Five-year survival for poor-prognosis cancers reaches the Nordic level', 'Huonoennusteisten syöpien 5 vuoden'),
                sind('Syöpäkuolleisuus pienenee 10 % (nykyisin 13 300 henkilöä vuodessa)', 'Cancer mortality falls by 10 % (currently 13,300 people a year)', 'Syöpäkuolleisuus pienenee 10 %'),
                sind('Potilaat pääsevät hoitoon tavoiteaikojen puitteissa***', 'Patients get treatment within the target times', 'Potilaat pääsevät hoitoon tavoiteaikojen'),
            ],
            'footnotes': [
                sind('** Viiden vuoden suhteellinen elossaolo kasvaa Nordcan-tilastossa esitetystä vuoden 2023 tasosta yli 14 prosenttiyksikköä keuhkosyövässä, 6 prosenttiyksikköä haimasyövässä ja 14 prosenttiyksikköä maksasyövässä. Pohjoismaisella tasolla viitataan Ruotsin ja Norjan keskiarvoon.',
                     'Five-year relative survival rises from the 2023 NORDCAN level by more than 14 percentage points in lung cancer, 6 in pancreatic and 14 in liver cancer. Nordic level means the mean of Sweden and Norway.', 'Viiden vuoden suhteellinen elossaolo kasvaa'),
                sind('*** THL (Ohjaus 21/2016). Hoitoonpääsyn seuranta syövän hoidossa.', 'Target times refer to THL Ohjaus 21/2016 (6 weeks from referral to first treatment when cancer is suspected).', 'THL (Ohjaus 21/2016)'),
            ]},
        'equality': {'indicators': [sind('Alueelliset ja sosioekonomiset erot syövän ilmaantuvuudessa, hoidossa ja syöpäkuolleisuudessa ovat käytettävissä palvelutoiminnassa ja niillä ohjataan toimintaa',
                                         'Regional and socioeconomic differences in cancer incidence, care and mortality are available to services and used to steer them', 'Alueelliset ja sosioekonomiset erot')]},
    },
}


# ---------------------------------------------------------------- verify quotes against saved copies
def norm(s):
    s = s.replace('&lt;', '<').replace('­', '')
    return re.sub(r'[\s|+\-–-]+', ' ', s).strip().lower()


def check_quotes():
    cache, bad = {}, []
    for slug, q in CHECKS:
        if slug not in cache:
            cache[slug] = norm(open(f'{RAW}/{slug}/page.txt', encoding='utf-8', errors='replace').read())
        if norm(q) not in cache[slug]:
            bad.append((slug, q[:90]))
    return bad


bad = check_quotes()
for b in bad:
    print('QUOTE NOT FOUND', b)
if bad:
    raise SystemExit(1)
for name, obj in (('parameters', parameters), ('interventions', interventions), ('roadmap_measures', roadmap)):
    json.dump(obj, open(f'{OUT}/{name}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def count(o, acc):
    if isinstance(o, dict):
        if 'verified' in o and 'url' in o:
            acc[bool(o['verified'])] += 1
        for v in o.values():
            count(v, acc)
    elif isinstance(o, list):
        for v in o:
            count(v, acc)
    return acc


print('quotes checked:', len(CHECKS))
print('parameters verified/unverified:', count(parameters, {True: 0, False: 0}))
print('interventions evidence verified/unverified:', count(interventions, {True: 0, False: 0}), 'n interventions', len(interventions))
print('roadmap measures:', len(measures), 'with budget:', sum(1 for m in measures if m['budget_eur']))
