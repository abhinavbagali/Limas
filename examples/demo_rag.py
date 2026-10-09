from context_compressor.compression.compressor import ContextCompressor


def main() -> None:
    query = "How does climate change affect precipitation?"
    docs = [
        "Climate change alters the global hydrological cycle by increasing evaporation and changing storm tracks.",
        "The office kitchen is closed on Fridays.",
        "Warmer temperatures intensify evaporation, which can increase rainfall in some regions and reduce it in others.",
    ]

    compressor = ContextCompressor()
    result = compressor.compress(query=query, documents=docs, max_tokens=80)

    print("Compressed context:")
    print(result.compressed_text)
    print(f"Original context words (estimated): {result.estimated_original_word_count}")
    print(f"Compressed context words (estimated): {result.estimated_compressed_word_count}")
    print(f"Word-count reduction (estimated): {result.estimated_word_reduction_percent:.2f}%")


if __name__ == "__main__":
    main()
