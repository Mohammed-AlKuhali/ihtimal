/* Arabic names + dot colours + country flag for the clubs on the site (fallback when the JSON has no `ar` / `colour`).
   Crests live in assets/logos/<team id>.png (ESPN images resized to 96x96, see assets/logos/CREDITS.md); a club with no crest file
   falls back to its coloured dot. Lookup is by normalised English name / id (see normName in app.js). */
(function () {
  var DROP = { fc:1, cf:1, afc:1, sfc:1, sc:1, ac:1, as:1, aj:1, ssc:1, rc:1, rcd:1, cd:1, ud:1, club:1, the:1, saudi:1, calcio:1 };
  function normName(s) {
    return String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/&/g, ' and ').split(/[^a-z0-9]+/).filter(function (w) { return w && !DROP[w]; }).join('');
  }
  // [English name, Arabic, dot colour, comma-separated aliases]; a bare string row sets the country flag (assets/flags/<code>.svg) for the rows after it
  var LIST = [
    // Saudi Pro League
    'sa',
    ['Al Hilal','الهلال','#3F7CE0','hilal'], ['Al Nassr','النصر','#F5C518','nassr'], ['Al Ittihad','الاتحاد','#F2C200','ittihad'],
    ['Al Ahli','الأهلي','#1FA463','ahli,alahlisaudi'], ['Al Qadsiah','القادسية','#F29A1F','qadsiah,qadisiya,alqadisiyah'],
    ['Al Shabab','الشباب','#E5E7EB','shabab'], ['Al Ettifaq','الاتفاق','#2FA44F','ettifaq'], ['Al Taawoun','التعاون','#F59E0B','taawoun'],
    ['Al Fayha','الفيحاء','#3DBE6B','fayha'], ['Al Fateh','الفتح','#1AA39A','fateh'], ['Al Khaleej','الخليج','#5FB760','khaleej'],
    ['Al Hazem','الحزم','#D64045','hazem'], ['Al Riyadh','الرياض','#4C8DF6','riyadh'], ['Al Faisaly','الفيصلي','#D7263D','faisaly'],
    ['Al Diriyah','الدرعية','#B5547A','diriyah'], ['Neom SC','نيوم','#F2B705','neom'], ['Abha','أبها','#E0524A',''],
    ['Al Kholood','الخلود','#9A86D9','kholood'], ['Damac','ضمك','#C97B3D',''], ['Al Okhdood','الأخدود','#8A9BB0','okhdood,alakhdoud'],
    ['Al Orobah','العروبة','#6BBF59','orobah'], ['Al Najma','النجمة','#E8C14B','najma'], ['Al Raed','الرائد','#E0554F','raed'],
    // Premier League
    'gb-eng',
    ['AFC Bournemouth','بورنموث','#E5484D','bournemouth'], ['Arsenal','أرسنال','#EF2B2D',''], ['Aston Villa','أستون فيلا','#9CC3E6','villa'],
    ['Brentford','برينتفورد','#E5484D',''], ['Brighton & Hove Albion','برايتون','#3B82F6','brighton'], ['Chelsea','تشيلسي','#2F6FD6',''],
    ['Coventry City','كوفنتري سيتي','#6EC1E4','coventry'], ['Crystal Palace','كريستال بالاس','#3B6FD6','palace'], ['Everton','إيفرتون','#3B6FD6',''],
    ['Fulham','فولهام','#E5E7EB',''], ['Hull City','هال سيتي','#F5A524','hull'], ['Ipswich Town','إيبسويتش تاون','#3B82F6','ipswich'],
    ['Leeds United','ليدز يونايتد','#FFD21F','leeds'], ['Liverpool','ليفربول','#D81E3A',''], ['Manchester City','مانشستر سيتي','#6CABDD','mancity'],
    ['Manchester United','مانشستر يونايتد','#E5484D','manutd,manunited'], ['Newcastle United','نيوكاسل يونايتد','#D1D5DB','newcastle'],
    ['Nottingham Forest','نوتنغهام فورست','#E5484D','nottmforest,forest'], ['Sunderland','سندرلاند','#E5484D',''],
    ['Tottenham Hotspur','توتنهام هوتسبير','#E5E7EB','tottenham,spurs'], ['Burnley','بيرنلي','#A5476B',''], ['Wolverhampton Wanderers','وولفرهامبتون','#FDB913','wolves'],
    ['West Ham United','وست هام يونايتد','#B0506B','westham'], ['Leicester City','ليستر سيتي','#3B82F6','leicester'], ['Southampton','ساوثهامبتون','#E5484D',''],
    // La Liga
    'es',
    ['Alaves','ألافيس','#4C8DF6','deportivoalaves'], ['Athletic Club','أتلتيك بلباو','#E5484D','athleticbilbao,athletic'], ['Atletico Madrid','أتلتيكو مدريد','#E5484D','atletico,atleticodemadrid'],
    ['Barcelona','برشلونة','#C8245F','fcbarcelona,barca'], ['Celta Vigo','سيلتا فيغو','#7DB7E8','celta,celtadevigo'], ['Deportivo','ديبورتيفو لا كورونيا','#4C8DF6','deportivolacoruna,deportivodelacoruna'],
    ['Elche','إلتشي','#3DBE6B',''], ['Espanyol','إسبانيول','#4C8DF6',''], ['Getafe','خيتافي','#4C8DF6',''], ['Levante','ليفانتي','#D64045','levanteud'],
    ['Malaga','مالقة','#7DB7E8',''], ['Osasuna','أوساسونا','#D64045',''], ['Racing Santander','راسينغ سانتاندير','#3DBE6B','racing,realracingclub'],
    ['Rayo Vallecano','رايو فاييكانو','#E5484D','rayo'], ['Real Betis','ريال بيتيس','#3DBE6B','betis'], ['Real Madrid','ريال مدريد','#F3F4F6','madrid'],
    ['Real Sociedad','ريال سوسيداد','#4C8DF6','sociedad'], ['Sevilla','إشبيلية','#F3F4F6',''], ['Valencia','فالنسيا','#F5A524',''], ['Villarreal','فياريال','#FFD21F',''],
    ['Girona','جيرونا','#E5484D',''], ['Mallorca','ريال مايوركا','#D64045','realmallorca'], ['Real Oviedo','ريال أوفييدو','#4C8DF6','oviedo'], ['Las Palmas','لاس بالماس','#FFD21F',''],
    // Ligue 1
    'fr',
    ['AJ Auxerre','أوكسير','#4C8DF6','auxerre'], ['AS Monaco','موناكو','#E5484D','monaco'], ['Angers','أنجيه','#E5E7EB','angerssco'], ['Brest','بريست','#E5484D','stadebrestois'],
    ['Le Havre AC','لو هافر','#6EC1E4','lehavre,havre'], ['Le Mans','لو مان','#E5484D','lemansfc'], ['Lens','لانس','#FFD21F','rclens'], ['Lille','ليل','#E5484D','losclille,lillosc'],
    ['Lorient','لوريان','#F59E0B','fclorient'], ['Lyon','ليون','#4C8DF6','olympiquelyonnais,olympiquelyon'], ['Marseille','مارسيليا','#6EC1E4','olympiquedemarseille,olympiquemarseille'],
    ['Nice','نيس','#E5484D','ogcnice'], ['Paris FC','باريس إف سي','#4C8DF6','parisfc'], ['Paris Saint-Germain','باريس سان جيرمان','#3B6FE0','psg,parissg'],
    ['Stade Rennais','رين','#E5484D','rennes'], ['Strasbourg','ستراسبورغ','#4C8DF6','rcstrasbourg'], ['Toulouse','تولوز','#A58BE0','toulousefc'], ['Troyes','تروا','#4C8DF6','estactroyes'],
    ['Metz','ميتز','#C14A5A','fcmetz'], ['Nantes','نانت','#F2C200','fcnantes'],
    // Featured opponents
    'de',
    ['Bayern Munich','بايرن ميونخ','#E0303B','bayern,bayernmunchen,fcbayernmunchen,bayernmunich']
  ];
  var MAP = {}, LOGO = {}, FLAGS = { sa: 1, 'gb-eng': 1, es: 1, fr: 1, de: 1 }, country = null;
  LIST.forEach(function (r) {
    if (typeof r === 'string') { country = r; return; }
    var rec = { en: r[0], ar: r[1], colour: r[2], flag: country };
    [r[0]].concat(r[3] ? r[3].split(',') : []).forEach(function (k) { MAP[normName(k)] = rec; });
  });
  // [team id, English name] for every crest file in assets/logos/ (one per club that appears in site/data)
  var LOGO_FILES = [
    ["abha", "Abha"],
    ["afc-bournemouth", "Bournemouth"],
    ["aj-auxerre", "Auxerre"],
    ["al-ahli", "Al Ahli"],
    ["al-diriyah", "Al-Diriyah"],
    ["al-ettifaq", "Al Ettifaq"],
    ["al-faisaly", "Al Faisaly"],
    ["al-fateh", "Al Fateh"],
    ["al-fayha", "Al Fayha"],
    ["al-hazem", "Al Hazem"],
    ["al-hilal", "Al Hilal"],
    ["al-ittihad", "Al Ittihad"],
    ["al-khaleej", "Al Khaleej"],
    ["al-kholood", "Al Kholood"],
    ["al-nassr", "Al Nassr"],
    ["al-qadsiah", "Al Qadsiah"],
    ["al-riyadh", "Al Riyadh"],
    ["al-shabab", "Al Shabab"],
    ["al-taawoun", "Al Taawoun"],
    ["alaves", "Alavés"],
    ["angers", "Angers"],
    ["arsenal", "Arsenal"],
    ["as-monaco", "Monaco"],
    ["aston-villa", "Aston Villa"],
    ["athletic-club", "Athletic Club"],
    ["atletico-madrid", "Atlético Madrid"],
    ["barcelona", "Barcelona"],
    ["bayern", "Bayern Munich"],
    ["brentford", "Brentford"],
    ["brest", "Brest"],
    ["brighton-hove-albion", "Brighton"],
    ["celta-vigo", "Celta Vigo"],
    ["chelsea", "Chelsea"],
    ["coventry-city", "Coventry City"],
    ["crystal-palace", "Crystal Palace"],
    ["deportivo", "Deportivo"],
    ["elche", "Elche"],
    ["espanyol", "Espanyol"],
    ["everton", "Everton"],
    ["fulham", "Fulham"],
    ["getafe", "Getafe"],
    ["hull-city", "Hull City"],
    ["ipswich-town", "Ipswich Town"],
    ["le-havre-ac", "Le Havre"],
    ["le-mans", "Le Mans"],
    ["leeds-united", "Leeds United"],
    ["lens", "Lens"],
    ["levante", "Levante"],
    ["lille", "Lille"],
    ["liverpool", "Liverpool"],
    ["lorient", "Lorient"],
    ["lyon", "Lyon"],
    ["malaga", "Málaga"],
    ["manchester-city", "Manchester City"],
    ["manchester-united", "Manchester United"],
    ["marseille", "Marseille"],
    ["neom", "NEOM"],
    ["newcastle-united", "Newcastle United"],
    ["nice", "Nice"],
    ["nottingham-forest", "Nottingham Forest"],
    ["osasuna", "Osasuna"],
    ["paris-fc", "Paris FC"],
    ["psg", "Paris Saint-Germain"],
    ["racing-santander", "Racing Santander"],
    ["rayo-vallecano", "Rayo Vallecano"],
    ["real-betis", "Real Betis"],
    ["real-madrid", "Real Madrid"],
    ["real-sociedad", "Real Sociedad"],
    ["sevilla", "Sevilla"],
    ["stade-rennais", "Rennes"],
    ["strasbourg", "Strasbourg"],
    ["sunderland", "Sunderland"],
    ["tottenham-hotspur", "Tottenham"],
    ["toulouse", "Toulouse"],
    ["troyes", "Troyes"],
    ["valencia", "Valencia"],
    ["villarreal", "Villarreal"]
  ];
  LOGO_FILES.forEach(function (f) {
    var rec = MAP[normName(f[0])] || MAP[normName(f[1])] || null;
    LOGO[normName(f[0])] = LOGO[normName(f[1])] = f[0];
    if (rec) for (var k in MAP) if (MAP[k] === rec) LOGO[k] = f[0];
  });
  window.TeamDict = {
    normName: normName,
    find: function () {
      for (var i = 0; i < arguments.length; i++) {
        var k = normName(arguments[i]);
        if (k && MAP[k]) return MAP[k];
      }
      return null;
    },
    // crest file name (without .png) for a team, or null when we have no crest for it
    logo: function () {
      for (var i = 0; i < arguments.length; i++) {
        var k = normName(arguments[i]);
        if (k && LOGO[k]) return LOGO[k];
      }
      return null;
    },
    hasFlag: function (code) { return !!FLAGS[code]; }
  };
})();
