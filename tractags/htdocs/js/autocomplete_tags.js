jQuery(function($) {
  var sep = tags.separator.trim() + ' ';
  function split( val ) {
    return val.split( /separator\s*|\s+/ );
  }
  function extractLast( term ) {
    return split( term ).pop();
  }
  $('#' + tags.autocomplete_field)
    // don't navigate away from field on tab when selecting
    // an item
    .bind( "keydown", function( event ) {
      if ( event.keyCode === $.ui.keyCode.TAB &&
        $( this ).data( "autocomplete" ).menu.active ) {
        event.preventDefault();
      }
    })
    .autocomplete({
      delay: 0,
      minLength: 0,
      source: function( request, response ) {
        // delegate back to autocomplete, but extract
        // the last term
        response( $.ui.autocomplete.filter(
          tags.keywords, extractLast( request.term ) ) );
      },
      focus: function() {
        // prevent value inserted on focus
        return false;
      },
      select: function( event, ui ) {
        var terms = split( this.value );
        // remove the current input
        terms.pop();
        // add the selected item
        terms.push( ui.item.value );
        // add placeholder to get the comma-and-space at
        // the end
        terms.push( "" );
        this.value = terms.join( sep );
        return false;
      }
    });
  if ( tags.help_href ) {
    var label = $('label[for="' + tags.autocomplete_field + '"]')
      .wrapInner($('<a>', {
        href: tags.help_href,
        target: tags.help_new_window ? 'blank' : null,
      }))
  }
});
