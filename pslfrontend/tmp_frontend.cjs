const fs = require('fs');
const path = require('path');

function replaceInFile(filePath) {
    if (!fs.existsSync(filePath)) return;
    let code = fs.readFileSync(filePath, 'utf8');
    let original = code;

    // Replace `/artwork/${artwork.token_id}` with `/artwork/${artwork.id || artwork.token_id}`
    code = code.replace(/to=\{\`\/artwork\/\$\{artwork\.token_id\}\`\}/g, "to={`/artwork/${artwork.id || artwork.token_id}`}");
    
    // Replace `/artwork/${license.token_id}` with `/artwork/${license.artwork_id || license.token_id}`
    code = code.replace(/to=\{\`\/artwork\/\$\{license\.token_id\}\`\}/g, "to={`/artwork/${license.artwork_id || license.token_id}`}");

    if (code !== original) {
        fs.writeFileSync(filePath, code);
        console.log(`Updated ${filePath}`);
    }
}

// Target files based on earlier findstr output
replaceInFile('src/pages/Explorer.jsx');
replaceInFile('src/pages/dashboard/ArtistDash/MyArtworks.jsx');
replaceInFile('src/pages/LicensesPage.jsx');

console.log('Frontend link migration completed.');
