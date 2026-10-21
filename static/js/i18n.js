/**
 * Client-side translation. The server injects window.I18N (the `js.*` catalog for the
 * page's language) -- there is no client-side fallback language, so a missing key is
 * shown as [[key]] and logged instead of silently mixing languages.
 */
function i18n(key, params) {
    const catalog = window.I18N || {};
    let text = catalog[key];
    if (text === undefined) {
        console.error('Missing translation:', key);
        return '[[' + key + ']]';
    }
    if (params) {
        Object.keys(params).forEach(function (name) {
            text = text.split('{' + name + '}').join(String(params[name]));
        });
    }
    return text;
}
