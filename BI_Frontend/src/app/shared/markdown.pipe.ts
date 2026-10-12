import { Pipe, PipeTransform } from '@angular/core';
import { marked } from 'marked';

marked.use({ gfm: true, breaks: false });

/**
 * Markdown → HTML for assistant answers. The result is bound with [innerHTML],
 * so Angular's built-in sanitizer strips scripts / event handlers.
 */
@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  transform(text: string | null | undefined): string {
    if (!text) return '';
    const html = marked.parse(text, { async: false }) as string;
    // Wrap tables so wide results scroll inside the bubble instead of the page.
    return html.replace(/<table>/g, '<div class="table-wrap"><table class="table">').replace(/<\/table>/g, '</table></div>');
  }
}
