// Persistent Qwen3-TTS worker for the pinned llama.cpp b11829 runtime.
// Requests are relative ASCII job directories on stdin; stdout is the protocol.
#include "arg.h"
#include "common.h"
#include "sampling.h"
#include "log.h"
#include "mtmd-helper.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>

int main(int argc, char ** argv) {
    common_params params;
    ggml_backend_load_all_from_path("runtime");
    common_init();
    if (!common_params_parse(argc, argv, params, LLAMA_EXAMPLE_TTS)) return 1;
    params.embedding = true;
    llama_backend_init();
    auto init = common_init_from_params(params);
    auto model = init->model();
    auto ctx = init->context();
    auto sampler = init->sampler(0);
    if (!model || !ctx || !sampler) return 1;
    const auto vocab = llama_model_get_vocab(model);
    const int n_vocab = llama_vocab_n_tokens(vocab);
    llama_token eos = LLAMA_TOKEN_NULL;
    for (llama_token t = 0; t < n_vocab; ++t) {
        if (std::string(llama_vocab_get_text(vocab, t)) == "<|codec_eos_token|>") eos = t;
    }
    if (eos == LLAMA_TOKEN_NULL || n_vocab <= 1024) return 1;
    auto mp = mtmd_context_params_default();
    mp.use_gpu = params.mmproj_use_gpu;
    mp.device = params.mmproj_device;
    mtmd::context_ptr projector(mtmd_init_from_file(params.mmproj.path.c_str(), model, mp));
    if (!projector) return 1;
    mtmd_helper::gen_audio gen;
    gen.init(ctx, projector.get());
    if (!gen.valid()) return 1;
    std::cout << "READY" << std::endl;
    std::string job;
    std::string speaker_key;
    mtmd::bitmap_ptr speaker;
    while (std::getline(std::cin, job)) {
        // Python creates these directories directly under the model package.
        if (job.empty() || job.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") != std::string::npos) return 1;
        std::ifstream input(job + "/text.txt", std::ios::binary);
        if (!input) return 1;
        std::string text((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
        std::ifstream key_file(job + "/reference.key");
        std::string key;
        std::getline(key_file, key);
        if (key.empty()) key = job;
        if (!speaker || key != speaker_key) {
            auto reference = mtmd_helper_bitmap_init_from_file(projector.get(),
                (job + "/reference.wav").c_str(), false, mtmd_helper_init_opt_default());
            if (!reference.bitmap) return 1;
            speaker.reset(reference.bitmap);
            speaker_key = key;
        }
        llama_memory_clear(llama_get_memory(ctx), true);
        common_sampler_reset(sampler);
        auto request = mtmd_helper_gen_audio_inp_default();
        request.prompt = text.c_str();
        request.prompt_len = text.size();
        request.speaker_ref = speaker.get();
        request.lang = params.tts_lang.c_str();
        request.top_k = params.sampling.top_k;
        request.top_p = params.sampling.top_p;
        request.seed = params.sampling.seed;
        if (gen.set_input(&request)) return 1;
        int remaining;
        do {
            remaining = gen.step_prompt(params.n_batch);
            if (remaining < 0) return 1;
        } while (remaining);
        int frames = 0;
        auto sample = [&]() {
            // Match Qwen's reference generate(): reserved codec tokens are not
            // speech; only EOS is allowed, after at least two audio frames.
            auto logits = llama_get_logits_ith(ctx, -1);
            for (llama_token t = n_vocab - 1024; t < n_vocab; ++t) {
                if (t != eos || frames < 2) logits[t] = -std::numeric_limits<float>::infinity();
            }
            auto token = common_sampler_sample(sampler, ctx, -1);
            common_sampler_accept(sampler, token, true);
            return token;
        };
        auto token = sample();
        const float * hidden = llama_get_embeddings_ith(ctx, -1);
        bool stop = false;
        const int limit = params.n_predict > 0 ? params.n_predict : 512;
        while (!stop && frames < limit) {
            const float * next = nullptr;
            if (gen.step_gen(token, hidden, &next, &stop)) return 1;
            if (!next) break;
            ++frames;
            hidden = next;
            token = sample();
            if (frames % 24 == 0) std::cout << "PROGRESS " << frames << std::endl;
        }
        int32_t rate;
        const char * data;
        size_t bytes;
        int64_t samples;
        if (gen.get_output(&rate, &data, &bytes, &samples)) return 1;
        std::ofstream output(job + "/result.wav", std::ios::binary);
        output.write(data, bytes);
        output.close();
        if (!output) return 1;
        // The next sampled token can already be EOS at the frame boundary.
        std::cout << "DONE " << frames << " " << ((stop || token == eos) ? "eos" : "limit") << std::endl;
    }
    return 0;
}
