"""Built-in demo scripts so the pipeline runs with zero API keys."""

DEMO_SHORT = {
    "title": "Inflation kya hai? Paise ki value kyun ghat jaati hai",
    "hook": "Aapke paise ki value chupchap ghat rahi hai",
    "category": "finance",
    "format": "shorts",
    "scenes": [
        {"say": "क्या आपने कभी सोचा है कि पाँच साल पहले सौ रुपये में जो मिलता था, आज वो उतने में क्यों नहीं मिलता?",
         "caption": "Kya 5 saal pehle 100 rupaye mein jo milta tha, aaj wo kyun nahi milta?",
         "label": "Inflation", "image": "a shopping basket that has become smaller while the same stack of coins sits beside it", "keywords": ["grocery"]},
        {"say": "इसी को इन्फ्लेशन कहते हैं। यानी समय के साथ चीज़ों के दाम धीरे धीरे बढ़ते जाना।",
         "caption": "Isi ko inflation kehte hain. Samay ke saath cheezon ke daam badhte jaate hain.",
         "label": "Daam badhte hain", "image": "price tags rising like steps of a staircase in warm light", "keywords": ["market"]},
        {"say": "इसलिए सिर्फ़ पैसे रखना काफ़ी नहीं। ये भी सोचना ज़रूरी है कि आपकी बचत महँगाई के सामने टिक पा रही है या नहीं।",
         "caption": "Sirf paise rakhna kaafi nahi. Ye bhi sochna zaroori hai ki bachat mehngai ke saamne tik pa rahi hai ya nahi.",
         "label": "Bachat vs mehngai", "image": "a small plant standing firm beside a rising wave of water", "keywords": ["wave"]},
        {"say": "ये सिर्फ़ शैक्षणिक जानकारी है। निवेश सलाह नहीं। रोज़ एक नया कॉन्सेप्ट समझने के लिए फॉलो करो।",
         "caption": "Ye sirf educational jaankari hai, investment salah nahi. Roz ek naya concept ke liye follow karo.",
         "label": "", "image": "a glowing lightbulb above a neat stack of coins", "keywords": ["lightbulb"]}
    ]
}

DEMO_LONG = {
    "title": "Share Market kya hai? Beginners ke liye complete guide",
    "description": "Is video mein hum share market ke basic concepts ko aasaan Hinglish mein samjhenge.",
    "tags": ["share market", "stock market", "finance", "hinglish"],
    "hook": "Share market sun ke darta hai? Aaj sab clear ho jaayega.",
    "category": "finance",
    "format": "longform",
    "sections": [
        {"title": "Share Market kya hota hai?",
         "narration": "Socho ek company ka kaam achha chal raha hai. Wo bada hona chahti hai. Lekin uske paas paisa nahi hai. To wo kya karti hai? Wo apna kuch hissa logon ko bechti hai. Isi hisse ko share kehte hain. Jo log ye share khareedta hain, wo us company ke thode se maalik ban jaate hain.",
         "visuals": ["company building animation","people buying shares","stock exchange hall"],
         "image": "a stylized building splitting into many small glowing pieces being handed to different people",
         "keywords": ["building","office"]},
        {"title": "Share ka daam kyun badhta aur ghatta hai?",
         "narration": "Jab bahut log ek share khareedna chahte hain, to uska daam badhta hai. Aur jab log bechna chahte hain, to daam girta hai. Agar company ka kaam achha chal raha ho, company ka profit badh raha ho, to log us share mein dilchaspi dikhate hain. Isi wajah se daam badh sakta hai. Aur agar company ke results kharab ho, to daam gir sakta hai.",
         "visuals": ["seesaw animation","growing plant","falling leaves"],
         "image": "a seesaw with a glowing office building on one side and golden coins on the other",
         "keywords": ["seesaw","balance"]},
        {"title": "Sensex aur Nifty kya hai?",
         "narration": "Imagine karo ek class mein pachaas baache hain. Aap sabke number dekhne ki jagah sirf topper bachchon ke number dekhke puri class ka haal samajh lete ho. Usi tarah Nifty NSE ki pachaas badi companies ka ek group hai. Sensex BSE ki tees badi companies ka group hai. Jab in companies ke share ke daam average mein badhte hain, to index upar jaata hai.",
         "visuals": ["classroom with spotlight","thermometer","city skyline"],
         "image": "a glowing thermometer standing in front of a lit city skyline at night",
         "keywords": ["city skyline","night"]},
        {"title": "Kya share market mein risk hai?",
         "narration": "Haan, share market mein risk hota hai. Paisa badhne ki sambhavna bhi hoti hai, aur paisa kam hone ki bhi. Ye koi guarantee wali jagah nahi hai. Isiliye pehle samjho, phir sochi samjhi jagah par invest karo. Yaad rakho, ye video sirf educational information ke liye hai, investment advice nahi. Kisi bhi financial decision se pehle ek registered advisor se zaroor baat karo.",
         "visuals": ["warning sign","balance scale","advisor meeting"],
         "image": "an amber warning triangle made of light floating above a calm dark lake with no text",
         "keywords": ["lake","warning"]}
    ]
}


__all__ = ["DEMO_SHORT", "DEMO_LONG"]
