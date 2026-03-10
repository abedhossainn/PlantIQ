#!/usr/bin/env python3
"""
Step 2c: RAG Text Reformatter
Use Qwen2.5-32B-Instruct to reformat markdown to RAG-optimized format
Uses validation report from VLM comparison
"""

import json
import re
from pathlib import Path
import logging

# Import VLM infrastructure
from ..utils.vlm_options import VLMOptions
from ..utils.vlm_response_parser import parse_vlm_response, extract_json_from_text
from ..utils.progress_tracker import log_operation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_reformatter_prompt() -> str:
    """Load the RAG markdown reformatter system prompt"""
    prompt_path = Path(__file__).parent / "rag_markdown_reformatter_prompt.md"
    
    if not prompt_path.exists():
        logger.warning(f"⚠️  Prompt not found: {prompt_path}")
        return ""
    
    with open(prompt_path, 'r') as f:
        return f.read()


def reformat_with_qwen(
    markdown_content: str,
    validation_report: dict,
    pdf_path: str,
    doc_name: str,
    vlm_options: VLMOptions = None
) -> dict:
    """
    Use Qwen2.5-32B to reformat markdown for RAG
    
    Args:
        markdown_content: Markdown content to reformat
        validation_report: Validation feedback from VLM comparison
        pdf_path: Path to source PDF
        doc_name: Document name
        vlm_options: VLM configuration (uses default if None)
        
    Returns:
        Reformatted JSON with chunks
    """
    # Use default options if not provided (use text-only model settings)
    if vlm_options is None:
        vlm_options = VLMOptions.get_default("quality")
        vlm_options.model_id = "Qwen/Qwen2.5-32B-Instruct"  # Text model, not VLM
        vlm_options.max_new_tokens = 8000
        vlm_options.do_sample = False  # Deterministic output
    
    try:
        with log_operation("Text Reformatting", model=vlm_options.model_id, doc=doc_name):
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            import gc
            
            # Aggressive cleanup
            gc.collect()
            gc.collect()
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
            # Load tokenizer
            with log_operation("Load Tokenizer"):
                tokenizer = AutoTokenizer.from_pretrained(
                    vlm_options.model_id,
                    trust_remote_code=vlm_options.trust_remote_code
                )
            
            # Load model with VLM options
            with log_operation("Load Model"):
                model = AutoModelForCausalLM.from_pretrained(
                    vlm_options.model_id,
                    dtype=torch.float16,
                    device_map=vlm_options.device_map,
                    trust_remote_code=vlm_options.trust_remote_code,
                    max_memory={
                        0: f"{int(vlm_options.gpu_memory_fraction * 11)}GiB",
                        "cpu": "100GiB"
                    },
                    offload_folder="/tmp/offload"
                )
            
            # Use FULL markdown content - transformers handles batching efficiently
            # The validation report provides guidance; model will intelligently chunk it
            markdown_full = markdown_content
            
            # Build prompt
            system_prompt = load_reformatter_prompt()
            
            user_message = f"""Apply RAG optimization guidelines to this markdown content.

DOCUMENT: {doc_name}
MARKDOWN SIZE: {len(markdown_content)} characters
TOTAL CONTENT (process strategically):

{markdown_full}

VALIDATION FEEDBACK:
{json.dumps(validation_report, indent=2)}

TASK:
1. Reformat headings as questions
2. Apply the RAG markdown guidelines from the system prompt
3. Create RAG-optimized chunks with source citations for each section
4. Output valid JSON with chunks array covering the ENTIRE document
5. Ensure source page numbers are accurate for each chunk

Provide valid JSON output only."""
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            # Generate
            with log_operation("Generate Response", chars=len(user_message)):
                text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                if vlm_options.verbose:
                    logger.info(f"🔤 Token count: ~{len(text) // 4}")
                
                model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
                
                logger.info(f"🔄 Generating ({vlm_options.max_new_tokens} max tokens)...")
                
                # Use VLM options for generation
                gen_kwargs = vlm_options.get_generation_kwargs()
                gen_kwargs['use_cache'] = True
                
                with torch.no_grad():
                    generated_ids = model.generate(
                        **model_inputs,
                        **gen_kwargs
                    )
                
                generated_ids = [
                    output_ids[len(input_ids):] 
                    for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
                ]
                
                response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            # Cleanup model
            logger.info("🗑️  Unloading model from GPU...")
            del model
            del tokenizer
            gc.collect()
            torch.cuda.empty_cache()
            logger.info("✅ Model unloaded")
            
            # Parse JSON with structured parser
            with log_operation("Parse Response"):
                try:
                    # Try to extract JSON from response
                    extracted_json = extract_json_from_text(response)
                    if extracted_json:
                        # Validate it has expected structure
                        if "document_name" in extracted_json or "chunks" in extracted_json:
                            logger.info(f"✅ JSON parsed successfully")
                            return extracted_json
                        else:
                            logger.warning("⚠️  Extracted JSON missing expected fields")
                    
                    # Fallback to direct parse
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        result = json.loads(json_match.group())
                        logger.info(f"✅ JSON parsed successfully (fallback)")
                        return result
                    
                    # No valid JSON found
                    raise ValueError("No valid JSON found in response")
                    
                except Exception as e:
                    logger.error(f"⚠️  JSON parsing failed: {e}")
                    if vlm_options.verbose:
                        logger.debug(f"Response preview: {response[:500]}")
                    
                    return {
                        "document_name": doc_name,
                        "chunks": [],
                        "validation_summary": {"error": str(e), "raw_response": response[:500]}
                    }
    
    except Exception as e:
        logger.error(f"❌ Reformatting failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "document_name": doc_name,
            "chunks": [],
            "validation_summary": {"error": str(e)}
        }


def save_output(reformatted_json: dict, output_path: str):
    """Save RAG-optimized output"""
    output_path = Path(output_path)
    
    logger.info(f"💾 Saving to {output_path}")
    
    # Save JSON
    with open(output_path.with_suffix('.json'), 'w') as f:
        json.dump(reformatted_json, f, indent=2)
    
    logger.info(f"✅ Saved JSON: {output_path.with_suffix('.json')}")
    
    # Convert to markdown
    markdown_content = f"# {reformatted_json.get('document_name', 'Document')}\n\n"
    
    if "chunks" in reformatted_json:
        for chunk in reformatted_json["chunks"]:
            markdown_content += chunk.get("content", "") + "\n\n"
    
    with open(output_path.with_suffix('.md'), 'w') as f:
        f.write(markdown_content)
    
    logger.info(f"✅ Saved Markdown: {output_path.with_suffix('.md')}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="RAG text reformatter")
    parser.add_argument("pdf", help="Path to PDF")
    parser.add_argument("--markdown", default="output.md", help="Markdown file")
    parser.add_argument("--validation", default="validation_report.json", help="Validation report")
    parser.add_argument("--output", default="output_rag_optimized", help="Output base path")
    parser.add_argument("--config", help="VLM options config file (YAML or JSON)")
    parser.add_argument("--preset", choices=["balanced", "fast", "quality", "low_memory"],
                        default="quality", help="VLM preset configuration")
    
    args = parser.parse_args()
    
    # Load VLM options
    if args.config:
        if args.config.endswith('.yaml'):
            vlm_options = VLMOptions.from_yaml(args.config)
        else:
            vlm_options = VLMOptions.from_json(args.config)
    else:
        vlm_options = VLMOptions.get_default(args.preset)
        vlm_options.model_id = "Qwen/Qwen2.5-32B-Instruct"  # Text model
        vlm_options.max_new_tokens = 8000
        vlm_options.do_sample = False
    
    logger.info(f"Using VLM configuration: {args.preset if not args.config else args.config}")
    
    logger.info("=" * 80)
    logger.info("✨ Step 2c: RAG Text Reformatter")
    logger.info("=" * 80)
    
    # Load markdown
    logger.info("\n[1/4] Loading markdown...")
    with open(args.markdown, 'r') as f:
        markdown_content = f.read()
    logger.info(f"✅ Loaded {len(markdown_content)} characters")
    
    # Load validation report
    logger.info("\n[2/4] Loading validation report...")
    with open(args.validation, 'r') as f:
        validation_report = json.load(f)
    logger.info("✅ Validation report loaded")
    
    # Reformat with Qwen
    logger.info("\n[3/4] Reformatting with Qwen2.5-32B...")
    result = reformat_with_qwen(
        markdown_content,
        validation_report,
        args.pdf,
        Path(args.pdf).stem,
        vlm_options
    )
    
    # Save output
    logger.info("\n[4/4] Saving output...")
    save_output(result, args.output)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ RAG optimization complete!")
    logger.info("=" * 80)
    
    if "validation_summary" in result:
        logger.info(f"Summary: {result['validation_summary']}")


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
