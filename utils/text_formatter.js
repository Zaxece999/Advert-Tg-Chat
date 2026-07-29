function formatText(text, entities = []) {
    if (!text || !entities || entities.length === 0) {
        return processEmojis(text || '');
    }

    const sortedEntities = entities.sort((a, b) => {
        if (a.offset !== b.offset) {
            return a.offset - b.offset;
        }
        return b.length - a.length;
    });

    const tagEvents = [];

    for (const entity of sortedEntities) {
        const tags = getHtmlTags(entity);
        if (tags.open) {
            tagEvents.push({
                position: entity.offset,
                type: 'open',
                tag: tags.open,
                priority: entity.length,
                entityType: entity.type
            });
        }
        if (tags.close) {
            tagEvents.push({
                position: entity.offset + entity.length,
                type: 'close',
                tag: tags.close,
                priority: entity.length,
                entityType: entity.type
            });
        }
    }

    tagEvents.sort((a, b) => {
        if (a.position !== b.position) {
            return a.position - b.position;
        }
        if (a.type !== b.type) {
            return a.type === 'close' ? -1 : 1;
        }
        if (a.type === 'open') {
            return b.priority - a.priority;
        } else {
            return a.priority - b.priority;
        }
    });

    let result = '';
    let lastPosition = 0;

    for (const event of tagEvents) {
        if (event.position > lastPosition) {
            result += text.slice(lastPosition, event.position);
        }
        
        result += event.tag;
        lastPosition = event.position;
    }

    if (lastPosition < text.length) {
        result += text.slice(lastPosition);
    }

    return processEmojis(result);
}

function getHtmlTags(entity) {
    switch (entity.type) {
        case 'bold':
            return { open: '<b>', close: '</b>' };
        case 'italic':
            return { open: '<i>', close: '</i>' };
        case 'underline':
            return { open: '<u>', close: '</u>' };
        case 'strikethrough':
            return { open: '<s>', close: '</s>' };
        case 'code':
            return { open: '<code>', close: '</code>' };
        case 'pre':
            return { open: '<pre>', close: '</pre>' };
        case 'blockquote':
            return { open: '<blockquote>', close: '</blockquote>' };
        case 'spoiler':
            return { open: '<a href="spoiler">', close: '</a>' };
        case 'custom_emoji':
            return { 
                open: `<a href="emoji/${entity.custom_emoji_id}">`, 
                close: '</a>' 
            };
        case 'text_link':
            return { 
                open: `<a href="${entity.url}">`, 
                close: '</a>' 
            };
        case 'mention':
            return { open: '', close: '' };
        default:
            return { open: '', close: '' };
    }
}

function processEmojis(text) {
    let result = text.replace(/\[(\d+):([^\]]+)\]/g, (match, id, emoji) => {
        return `<a href="emoji/${id}">${emoji.trim()}</a>`;
    });

    result = escapeHtmlSafe(result);
    
    return result;
}

function escapeHtmlSafe(text) {
    const tagPlaceholders = {};
    let tagCounter = 0;

    function protectTag(match) {
        const placeholder = `__TAG_${tagCounter}__`;
        tagPlaceholders[placeholder] = match;
        tagCounter++;
        return placeholder;
    }

    const tagPattern = /<[^>]+>/g;
    text = text.replace(tagPattern, protectTag);

    text = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#x27;');

    for (const [placeholder, tag] of Object.entries(tagPlaceholders)) {
        text = text.replace(placeholder, tag);
    }

    return text;
}

function main() {
    let input = '';

    process.stdin.on('data', (chunk) => {
        input += chunk.toString();
    });

    process.stdin.on('end', () => {
        let data;
        try {
            data = JSON.parse(input);
            const result = formatText(data.text, data.entities);
            console.log(JSON.stringify({ result }));
        } catch (error) {
            console.error(JSON.stringify({
                error: error.message,
                result: (data && data.text) || ''
            }));
            process.exit(1);
        }
    });
}

if (require.main === module) {
    main();
}

module.exports = { formatText, processEmojis };
