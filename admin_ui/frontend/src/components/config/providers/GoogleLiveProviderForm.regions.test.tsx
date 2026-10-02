// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import axios from 'axios';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import GoogleLiveProviderForm from './GoogleLiveProviderForm';

vi.mock('axios');
vi.mock('../../../hooks/useConfirmDialog', () => ({
    useConfirmDialog: () => ({ confirm: vi.fn().mockResolvedValue(false) }),
}));

function FormHarness({ initialConfig }: { initialConfig: Record<string, unknown> }) {
    const [config, setConfig] = useState(initialConfig);
    return <>
        <GoogleLiveProviderForm providerKey="google_live" config={config} onChange={setConfig} />
        <div data-testid="saved-modalities">{String(config.response_modalities ?? '')}</div>
    </>;
}

describe('GoogleLiveProviderForm model-aware Vertex regions', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(axios.get).mockImplementation(async url => {
            if (url === '/api/config/vertex-ai/regions') {
                // An older backend catalog must not hide regions supported by the UI.
                return { data: { regions: [{ value: 'us-central1', label: 'US Central (Iowa)' }] } };
            }
            return { data: { credentials: { 'vertex-json': { uploaded: false } } } };
        });
    });

    it('shows all GA model regions and disables 3.8-incompatible choices', async () => {
        render(<FormHarness initialConfig={{ use_vertex_ai: true, llm_model: 'gemini-3.8-live', vertex_location: 'us-central1' }} />);
        const region = screen.getByLabelText('GCP Region') as HTMLSelectElement;

        expect(screen.getByRole('option', { name: 'US (multi-region)' })).toBeEnabled();
        expect(screen.getByRole('option', { name: 'EU (multi-region)' })).toBeEnabled();
        expect(screen.getByRole('option', { name: /US East \(South Carolina\).*unavailable/ })).toBeDisabled();
        expect(screen.getByRole('option', { name: /Europe North \(Finland\).*unavailable/ })).toBeDisabled();

        fireEvent.change(region, { target: { value: 'eu' } });
        expect(region.value).toBe('eu');
        expect(screen.getByRole('status')).toHaveTextContent('listed in eu');
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('preserves a compatible 2.5 region and resets it only when switching to 3.8', async () => {
        render(<FormHarness initialConfig={{ use_vertex_ai: true, llm_model: 'gemini-live-2.5-flash-native-audio', vertex_location: 'us-east1', response_modalities: 'text' }} />);
        const region = screen.getByLabelText('GCP Region') as HTMLSelectElement;
        const model = screen.getByLabelText('LLM Model') as HTMLSelectElement;

        expect(region.value).toBe('us-east1');
        expect(screen.getByLabelText('Response Modalities')).toBeEnabled();
        expect(screen.getByRole('option', { name: 'US East (South Carolina)' })).toBeEnabled();
        expect(screen.getByRole('option', { name: /US \(multi-region\).*unavailable/ })).toBeDisabled();

        fireEvent.change(model, { target: { value: 'gemini-3.8-live' } });
        expect(region.value).toBe('us-central1');
        expect(screen.getByLabelText('Response Modalities')).toBeDisabled();
        expect((screen.getByLabelText('Response Modalities') as HTMLSelectElement).value).toBe('audio');
        expect(screen.getByTestId('saved-modalities')).toHaveTextContent('audio');
        expect(screen.getByRole('status')).toHaveTextContent('listed in us-central1');
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('resets a multi-region selection when switching from 3.8 to 2.5', async () => {
        render(<FormHarness initialConfig={{ use_vertex_ai: true, llm_model: 'gemini-3.8-live', vertex_location: 'eu' }} />);
        fireEvent.change(screen.getByLabelText('LLM Model'), {
            target: { value: 'gemini-live-2.5-flash-native-audio' },
        });
        expect((screen.getByLabelText('GCP Region') as HTMLSelectElement).value).toBe('us-central1');
        expect(screen.getByLabelText('Response Modalities')).toBeEnabled();
        expect(screen.getByRole('option', { name: /EU \(multi-region\).*unavailable/ })).toBeDisabled();
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('normalizes an existing 3.8 Text Only setting when the form opens', async () => {
        render(<FormHarness initialConfig={{
            use_vertex_ai: true,
            llm_model: 'gemini-3.8-live',
            vertex_location: 'us-central1',
            response_modalities: 'text',
        }} />);
        expect(screen.getByLabelText('Response Modalities')).toBeDisabled();
        expect((screen.getByLabelText('Response Modalities') as HTMLSelectElement).value).toBe('audio');
        await waitFor(() => expect(screen.getByTestId('saved-modalities')).toHaveTextContent('audio'));
    });

    it('chooses a shared region when toggling to Vertex changes the model', async () => {
        render(<FormHarness initialConfig={{
            use_vertex_ai: false,
            llm_model: 'gemini-2.5-flash-native-audio-latest',
            vertex_location: 'eu',
        }} />);
        fireEvent.click(screen.getByLabelText('Use Vertex AI (Enterprise / GCP)'));

        expect((screen.getByLabelText('LLM Model') as HTMLSelectElement).value)
            .toBe('gemini-live-2.5-flash-native-audio');
        expect((screen.getByLabelText('GCP Region') as HTMLSelectElement).value).toBe('us-central1');
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('keeps a valid 3.8 multi-region when toggling to Vertex', async () => {
        render(<FormHarness initialConfig={{
            use_vertex_ai: false,
            llm_model: 'gemini-3.8-live',
            vertex_location: 'us',
        }} />);
        fireEvent.click(screen.getByLabelText('Use Vertex AI (Enterprise / GCP)'));

        expect((screen.getByLabelText('LLM Model') as HTMLSelectElement).value).toBe('gemini-3.8-live');
        expect((screen.getByLabelText('GCP Region') as HTMLSelectElement).value).toBe('us');
        expect(screen.getByRole('status')).toHaveTextContent('listed in us');
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('flags a saved invalid region without silently changing it on form load', async () => {
        render(<FormHarness initialConfig={{ use_vertex_ai: true, llm_model: 'gemini-3.8-live', vertex_location: 'us-east1' }} />);
        expect((screen.getByLabelText('GCP Region') as HTMLSelectElement).value).toBe('us-east1');
        expect(screen.getByLabelText('GCP Region')).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByRole('alert')).toHaveTextContent('not listed in us-east1');
        expect(screen.getByRole('alert').querySelector('a')).toHaveAttribute(
            'href', 'https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live',
        );
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });

    it('does not claim published availability for a legacy preview model', async () => {
        render(<FormHarness initialConfig={{
            use_vertex_ai: true,
            llm_model: 'gemini-live-2.5-flash-preview-native-audio-09-2025',
            vertex_location: 'us-central1',
        }} />);
        expect(screen.getByRole('status')).toHaveTextContent('not verified');
        expect(screen.getByRole('option', { name: 'US East (South Carolina)' })).toBeEnabled();
        await waitFor(() => expect(axios.get).toHaveBeenCalled());
    });
});
