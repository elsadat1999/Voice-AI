export const GOOGLE_LIVE_DEFAULT_MODEL = 'gemini-2.5-flash-native-audio-latest';

type GoogleLiveModelGroup = 'Gemini Developer API' | 'Vertex AI Live API' | 'Both Google APIs';

type GoogleLiveModelOption = {
    value: string;
    label: string;
};

type GoogleLiveModelSection = {
    label: GoogleLiveModelGroup;
    options: GoogleLiveModelOption[];
};

export const GOOGLE_LIVE_MODEL_GROUPS: GoogleLiveModelSection[] = [
    {
        label: 'Both Google APIs',
        options: [
            { value: 'gemini-3.8-live', label: 'Gemini 3.8 Live (GA)' },
        ],
    },
    {
        label: 'Gemini Developer API',
        options: [
            { value: 'gemini-2.5-flash-native-audio-latest', label: 'Gemini 2.5 Flash Native Audio (Latest)' },
            { value: 'gemini-2.5-flash-native-audio-preview-12-2025', label: 'Gemini 2.5 Flash Native Audio (Dec 2025)' },
            { value: 'gemini-2.5-flash-native-audio-preview-09-2025', label: 'Gemini 2.5 Flash Native Audio (Sep 2025)' },
            {
                value: 'gemini-3.1-flash-live-preview',
                label: 'Gemini 3.1 Flash Live Preview',
            },
        ],
    },
    {
        label: 'Vertex AI Live API',
        options: [
            { value: 'gemini-live-2.5-flash-native-audio', label: 'Gemini Live 2.5 Flash Native Audio (GA)' },
            { value: 'gemini-live-2.5-flash-preview-native-audio-09-2025', label: 'Gemini Live 2.5 Flash Native Audio (Preview 09-2025)' },
        ],
    },
];

export const GOOGLE_LIVE_MODEL_OPTIONS = GOOGLE_LIVE_MODEL_GROUPS.flatMap((group) => group.options);
export const GOOGLE_LIVE_SUPPORTED_MODELS = GOOGLE_LIVE_MODEL_OPTIONS.map((model) => model.value);

// Keep all locations used by the supported Live model catalog visible. The
// model-specific support check below disables the locations a model cannot use.
export const GOOGLE_LIVE_VERTEX_REGIONS = [
    { value: 'us', label: 'US (multi-region)' },
    { value: 'eu', label: 'EU (multi-region)' },
    { value: 'us-central1', label: 'US Central (Iowa)' },
    { value: 'us-east1', label: 'US East (South Carolina)' },
    { value: 'us-east4', label: 'US East (Northern Virginia)' },
    { value: 'us-east5', label: 'US East (Ohio)' },
    { value: 'us-south1', label: 'US South (Texas)' },
    { value: 'us-west1', label: 'US West (Oregon)' },
    { value: 'us-west4', label: 'US West (Las Vegas)' },
    { value: 'europe-central2', label: 'Europe Central (Warsaw)' },
    { value: 'europe-north1', label: 'Europe North (Finland)' },
    { value: 'europe-southwest1', label: 'Europe Southwest (Madrid)' },
    { value: 'europe-west1', label: 'Europe West (Belgium)' },
    { value: 'europe-west2', label: 'Europe West (London)' },
    { value: 'europe-west3', label: 'Europe West (Frankfurt)' },
    { value: 'europe-west4', label: 'Europe West (Netherlands)' },
    { value: 'europe-west8', label: 'Europe West (Milan)' },
    { value: 'asia-east1', label: 'Asia East (Taiwan)' },
    { value: 'asia-northeast1', label: 'Asia Northeast (Tokyo)' },
    { value: 'asia-southeast1', label: 'Asia Southeast (Singapore)' },
    { value: 'australia-southeast1', label: 'Australia (Sydney)' },
] as const;

// Model references:
// https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live
// https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-live-api
export const GOOGLE_LIVE_VERTEX_MODEL_REGIONS: Record<string, readonly string[]> = {
    'gemini-3.8-live': ['us-central1', 'us', 'eu'],
    'gemini-live-2.5-flash-native-audio': [
        'us-central1', 'us-east1', 'us-east4', 'us-east5', 'us-south1', 'us-west1', 'us-west4',
        'europe-central2', 'europe-north1', 'europe-southwest1', 'europe-west1', 'europe-west4', 'europe-west8',
    ],
};

export function getGoogleLiveVertexRegionSupport(
    model: unknown,
    useVertex: boolean,
    region: unknown,
): 'supported' | 'unsupported' | 'unknown' | null {
    if (!useVertex) return null;
    const normalizedModel = normalizeGoogleLiveModelForUi(model);
    const supportedRegions = Object.prototype.hasOwnProperty.call(GOOGLE_LIVE_VERTEX_MODEL_REGIONS, normalizedModel)
        ? GOOGLE_LIVE_VERTEX_MODEL_REGIONS[normalizedModel]
        : undefined;
    if (!supportedRegions) return 'unknown';
    const selectedRegion = typeof region === 'string' && region.trim() ? region.trim() : 'us-central1';
    return supportedRegions.includes(selectedRegion) ? 'supported' : 'unsupported';
}

export function preferredGoogleLiveVertexRegion(model: unknown, currentRegion: unknown): string {
    const selectedRegion = typeof currentRegion === 'string' && currentRegion.trim() ? currentRegion.trim() : 'us-central1';
    return getGoogleLiveVertexRegionSupport(model, true, selectedRegion) === 'unsupported'
        ? 'us-central1'
        : selectedRegion;
}

export function isGoogleLiveModelCompatible(model: string, useVertex: boolean): boolean {
    const normalized = normalizeGoogleLiveModelForUi(model);
    const group = GOOGLE_LIVE_MODEL_GROUPS.find(section =>
        section.options.some(option => option.value === normalized)
    );
    if (group?.label === 'Both Google APIs') return true;
    if (group) return useVertex ? group.label === 'Vertex AI Live API' : group.label === 'Gemini Developer API';
    // Retain the prior behavior for custom model names.
    return useVertex ? normalized.startsWith('gemini-live-') : !normalized.startsWith('gemini-live-');
}

export const GOOGLE_LIVE_LEGACY_MODEL_MAP: Record<string, string> = {
    'gemini-live-2.5-flash-preview': GOOGLE_LIVE_DEFAULT_MODEL,
};

export function normalizeGoogleLiveModelForUi(model: unknown): string {
    let raw = typeof model === 'string' ? model.trim() : '';
    if (raw.startsWith('models/')) {
        raw = raw.slice(7);
    }

    if (!raw) {
        return GOOGLE_LIVE_DEFAULT_MODEL;
    }

    if (Object.prototype.hasOwnProperty.call(GOOGLE_LIVE_LEGACY_MODEL_MAP, raw)) {
        return GOOGLE_LIVE_LEGACY_MODEL_MAP[raw];
    }

    // Always preserve the operator-configured model name.
    // Unknown models render in the "Custom" optgroup so the user
    // can see exactly what is configured and change it if needed.
    return raw;
}
