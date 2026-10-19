# Pinecone integrated-embedding index (ADR-0087). Integrated embedding still requires the spec + embed
# style in provider v5 (research section 4.3). The Starter plan is AWS us-east-1 only.
# field_map text = chunk_text matches vsia.retrieval.PINECONE_TEXT_FIELD.
#
# vsia.retrieval.PineconeStore creates the same index when it is missing. If the API created it first,
# import it instead of applying: terraform import 'pinecone_index.vsia[0]' vsia
#
# Warning: terraform destroy deletes the index and every stored record.

resource "pinecone_index" "vsia" {
  count = var.manage_pinecone_index ? 1 : 0

  name = var.pinecone_index_name
  spec = {
    serverless = {
      cloud  = "aws"
      region = "us-east-1"
    }
  }
  embed = {
    model = "llama-text-embed-v2"
    field_map = {
      text = "chunk_text"
    }
  }
}
